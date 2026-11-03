"""Decide which monitor a command means, what it is, and how to reach it.

This only reads sysfs and the config. Nothing here talks to a monitor.
"""

from dataclasses import dataclass
from typing import Literal
lazy from collections.abc import Mapping, Sequence

from freepilot.displays import SelectionError, select_display
from freepilot.features import FEATURE_SETS, FeatureSet, identify
lazy from freepilot.config import Alias
lazy from freepilot.ddcutil import Ddcutil
lazy from freepilot.displays import Display
lazy from freepilot.i2c import I2c
lazy from freepilot.vcp import Transport

type TransportName = Literal["ddcutil", "i2c"]


@dataclass(frozen=True, slots=True)
class Selection:
    """What the command line asked for. At most one of the first three is set."""

    display_number: str | None = None
    bus: int | None = None
    monitor: str | None = None
    transport: TransportName = "ddcutil"
    model: str | None = None


@dataclass(frozen=True, slots=True)
class Target:
    """The monitor a selection resolved to.

    display is None when sysfs can't say which monitor is meant: with
    --display, with a --bus no connector reports, or with no selector and
    several monitors. candidates then lists the monitors it could be.
    """

    display: Display | None
    features: FeatureSet
    candidates: tuple[Display, ...] = ()


def resolve(
    selection: Selection,
    connected: Sequence[Display],
    aliases: Mapping[str, Alias],
) -> Target:
    """Find the selected monitor and pick its feature set."""
    with_bus = tuple(display for display in connected if display.bus is not None)
    display: Display | None = None
    if selection.monitor:
        display = select_display(list(connected), selection.monitor, aliases)
    elif selection.bus is not None:
        display = next((d for d in connected if selection.bus in d.buses), None)
    elif selection.display_number is None and len(with_bus) == 1:
        display = with_bus[0]
    alias = aliases.get(selection.monitor) if selection.monitor else None
    model = selection.model or (alias.model if alias else None)
    return Target(display, feature_set(model, display), with_bus)


def feature_set(model: str | None, display: Display | None) -> FeatureSet:
    """Use an explicit model if given, else identify the monitor by its EDID."""
    if model is not None:
        return FEATURE_SETS[model]
    edid = display.edid if display else None
    return identify(edid.manufacturer if edid else None, edid.model if edid else None)


def connect(selection: Selection, target: Target) -> Transport:
    """Build the transport for a resolved target.

    freepilot hands ddcutil the bus it found for --monitor, so both
    transports pick the same monitor. Without a selector, ddcutil uses its
    own default display, and the i2c transport needs exactly one monitor.
    """
    if selection.display_number is not None:
        return Ddcutil(("--display", selection.display_number))
    bus = selected_bus(selection, target)
    if selection.transport == "i2c":
        return I2c(bus if bus is not None else only_bus(target))
    return Ddcutil() if bus is None else Ddcutil(("--bus", str(bus)))


def selected_bus(selection: Selection, target: Target) -> int | None:
    """Return the bus --bus or --monitor names, or None without either."""
    if selection.bus is not None:
        return selection.bus
    if not selection.monitor or target.display is None:
        return None
    if target.display.bus is None:
        message = f"{target.display.describe()} has no DDC bus in sysfs; try --bus"
        raise SelectionError(message)
    return target.display.bus


def only_bus(target: Target) -> int:
    """Return the bus of the only connected monitor, or explain why there isn't one."""
    match target.candidates:
        case [display] if display.bus is not None:
            return display.bus
        case []:
            message = "no connected monitor has a DDC bus in sysfs; pass --bus"
        case several:
            names = ", ".join(display.describe() for display in several)
            message = (
                f"several monitors are connected ({names}); pick one with --monitor"
            )
    raise SelectionError(message)
