"""Find connected monitors through sysfs, read their EDID, and pick one.

Discovery only reads sysfs, which needs no i2c permission. It never probes
a bus.
"""

import re
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Callable, Iterable, Mapping

from freepilot.errors import FreepilotError
lazy from freepilot.config import Alias

DRM_ROOT = Path("/sys/class/drm")
EDID_HEADER = bytes.fromhex("00ffffffffffff00")
EDID_BLOCK = 128
# The four 18-byte descriptors in the base block, and the display descriptor
# tags freepilot reads from them.
DESCRIPTOR_OFFSETS = (54, 72, 90, 108)
DESCRIPTOR_SERIAL, DESCRIPTOR_NAME = 0xFF, 0xFC
I2C_NAME = re.compile(r"i2c-(\d+)")


class EdidError(ValueError):
    """An EDID blob that is too short or fails its header or checksum."""


class SelectionError(FreepilotError):
    """--monitor matched no monitor, or more than one."""


@dataclass(frozen=True, slots=True)
class Edid:
    """The identity fields freepilot needs from an EDID base block.

    serial_number is the numeric serial from bytes 12-15, and serial the text
    serial descriptor. Monitors may fill in either, both, or neither.
    """

    manufacturer: str
    product: int
    serial_number: int | None = None
    serial: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class Display:
    """A connected monitor. buses lists DDC buses, best first; it may be empty."""

    connector: str
    buses: tuple[int, ...]
    edid: Edid | None

    @property
    def bus(self) -> int | None:
        """The bus freepilot uses, or None when sysfs gives none."""
        return self.buses[0] if self.buses else None

    @property
    def short_connector(self) -> str:
        """The connector without its card prefix, such as DP-1."""
        return self.connector.partition("-")[2]

    def describe(self) -> str:
        """Name the monitor for error messages."""
        model = self.edid.model if self.edid else None
        return f"{self.connector} ({model or 'unknown model'})"


def parse_edid(data: bytes) -> Edid:
    """Parse the base block of an EDID. Extension blocks are ignored."""
    if len(data) < EDID_BLOCK:
        message = f"EDID is {len(data)} bytes, expected at least {EDID_BLOCK}"
        raise EdidError(message)
    block = data[:EDID_BLOCK]
    if block[:8] != EDID_HEADER:
        message = "EDID header is wrong"
        raise EdidError(message)
    if sum(block) % 256:
        message = "EDID checksum does not match"
        raise EdidError(message)
    # Three 5-bit letters, A = 1, packed big-endian into bytes 8-9.
    word = int.from_bytes(block[8:10], "big")
    manufacturer = "".join(
        chr(ord("A") - 1 + (word >> shift & 0x1F)) for shift in (10, 5, 0)
    )
    texts = dict(descriptor_texts(block))
    return Edid(
        manufacturer=manufacturer,
        product=int.from_bytes(block[10:12], "little"),
        serial_number=int.from_bytes(block[12:16], "little") or None,
        serial=texts.get(DESCRIPTOR_SERIAL),
        model=texts.get(DESCRIPTOR_NAME),
    )


def descriptor_texts(block: bytes) -> Iterable[tuple[int, str]]:
    """Yield (tag, text) for each non-empty text display descriptor."""
    for offset in DESCRIPTOR_OFFSETS:
        descriptor = block[offset : offset + 18]
        # Display descriptors start with three zero bytes; detailed timings
        # start with a non-zero pixel clock.
        if descriptor[:3] != b"\0\0\0":
            continue
        text = descriptor[5:].partition(b"\n")[0].decode("ascii", "replace").strip()
        if text:
            yield descriptor[3], text


def find_displays(root: Path | None = None) -> list[Display]:
    """List connected monitors under a DRM sysfs root, in connector order."""
    displays = []
    for connector in sorted((root or DRM_ROOT).glob("card*-*")):
        try:
            connected = (connector / "status").read_text().strip() == "connected"
            edid_bytes = (connector / "edid").read_bytes() if connected else b""
        except OSError:
            # The connector went away while we looked at it.
            continue
        if connected:
            displays.append(
                Display(
                    connector.name, connector_buses(connector), read_edid(edid_bytes)
                )
            )
    return displays


def read_edid(data: bytes) -> Edid | None:
    """Parse EDID bytes, or return None when they are missing or unusable."""
    try:
        return parse_edid(data) if data else None
    except EdidError:
        return None


def connector_buses(connector: Path) -> tuple[int, ...]:
    """Find a connector's DDC buses: the ddc link first, then i2c-N children.

    On DisplayPort the ddc link and the AUX channel child are different buses.
    ddcutil prefers the ddc link, so freepilot does too.
    """
    ddc = connector / "ddc"
    names = [ddc.resolve().name] if ddc.exists() else []
    names.extend(child.name for child in sorted(connector.glob("i2c-*")))
    buses = [int(match[1]) for name in names if (match := I2C_NAME.fullmatch(name))]
    return tuple(dict.fromkeys(buses))


def select_display(
    displays: list[Display], selector: str, aliases: Mapping[str, Alias]
) -> Display:
    """Pick the one monitor a --monitor value names.

    Rules are tried in order: config alias, serial, full connector, short
    connector, model substring. The first rule that matches anything decides.
    Several matches is an error, never a reason to try the next rule.
    """
    if selector in aliases:
        alias = aliases[selector]
        return only_match(
            displays, f"alias {selector!r}", lambda d: alias_matches(alias, d)
        )
    rules: list[Callable[[Display], bool]] = [
        lambda d: serial_matches(d, selector),
        lambda d: d.connector == selector,
        lambda d: d.short_connector == selector,
        lambda d: model_contains(d, selector),
    ]
    for matches in rules:
        if any(matches(display) for display in displays):
            return only_match(displays, repr(selector), matches)
    message = f"no monitor matches {selector!r}; connected: {describe_all(displays)}"
    raise SelectionError(message)


def only_match(
    displays: list[Display], what: str, matches: Callable[[Display], bool]
) -> Display:
    """Return the single display that matches, or raise naming the candidates."""
    found = [display for display in displays if matches(display)]
    match found:
        case [display]:
            return display
        case []:
            message = f"{what} is not connected; connected: {describe_all(displays)}"
        case _:
            message = f"{what} matches several monitors: {describe_all(found)}"
    raise SelectionError(message)


def describe_all(displays: list[Display]) -> str:
    """List monitors for an error message."""
    return ", ".join(display.describe() for display in displays) or "none"


def serial_matches(display: Display, serial: str) -> bool:
    """Match the text serial or the numeric serial exactly."""
    edid = display.edid
    if edid is None:
        return False
    numeric = None if edid.serial_number is None else str(edid.serial_number)
    return serial in (edid.serial, numeric)


def model_contains(display: Display, text: str) -> bool:
    """Match part of the model name, ignoring case."""
    model = display.edid.model if display.edid else None
    return model is not None and text.casefold() in model.casefold()


def alias_matches(alias: Alias, display: Display) -> bool:
    """Match every key an alias sets."""
    if alias.serial is not None and not serial_matches(display, alias.serial):
        return False
    return alias.connector in {None, display.connector, display.short_connector}
