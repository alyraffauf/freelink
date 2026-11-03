"""Turn a profile into ordered writes, apply them, and save the current state."""

import json
import re
from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from freepilot.errors import FreepilotError
from freepilot.features import name_for
lazy from freepilot.config import Profile
lazy from freepilot.features import FeatureSet
lazy from freepilot.monitor import Monitor
lazy from freepilot.vcp import Reading

# Picture mode goes first because changing it resets levels on most
# monitors. Raw codes follow the named keys. Input goes last because it may
# switch the monitor away from this machine.
NAMED_ORDER = ("picture-mode", "brightness", "contrast", "sharpness", "volume", "mute")
LAST = ("input",)
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


class ProfileError(FreepilotError):
    """A profile write failed partway through."""


@dataclass(frozen=True, slots=True)
class Step:
    """One write in a profile, with the text that names it in reports."""

    code: int
    value: int
    label: str


def plan(profile: Profile, monitor: Monitor) -> list[Step]:
    """Resolve a profile to writes in apply order, checking names first."""
    steps = [
        step(monitor, name, profile.settings[name])
        for name in NAMED_ORDER
        if name in profile.settings
    ]
    steps += [
        Step(code, value, f"vcp 0x{code:02x} = {value}")
        for code, value in sorted(profile.vcp.items())
    ]
    steps += [
        step(monitor, name, profile.settings[name])
        for name in LAST
        if name in profile.settings
    ]
    return steps


def step(monitor: Monitor, name: str, value: int | str) -> Step:
    """Resolve one named setting against the monitor's feature set."""
    if isinstance(value, str):
        code, number = monitor.choice(name, value)
    else:
        code, number = monitor.code(name), value
    return Step(code, number, f"{name} {value}")


def apply(monitor: Monitor, steps: Sequence[Step]) -> None:
    """Write every step in one session, stopping at the first failure.

    --strict checks run for every step before the first write. The monitor
    never confirms a write, so the error says which writes were sent, not
    which applied, and nothing is rolled back.
    """
    if monitor.check is not None:
        for each in steps:
            monitor.check(each.code, each.value)
    sent: list[Step] = []
    with monitor.transport.session():
        for index, each in enumerate(steps):
            try:
                monitor.write(each.code, each.value)
            except FreepilotError as error:
                raise ProfileError(
                    failure_report(sent, each, steps[index + 1 :], error)
                ) from error
            sent.append(each)


def failure_report(
    sent: Sequence[Step], failed: Step, skipped: Sequence[Step], error: Exception
) -> str:
    """Say what was sent, what failed, and what was never tried."""
    parts = [f"{failed.label} failed and may or may not have applied: {error}"]
    if sent:
        parts.append(f"sent: {', '.join(each.label for each in sent)}")
    if skipped:
        parts.append(f"not attempted: {', '.join(each.label for each in skipped)}")
    return "; ".join(parts)


def save(name: str, status: Mapping[str, Reading | None], features: FeatureSet) -> str:
    """Write the current state as a [profiles.NAME] TOML table.

    Unreadable settings and unnamed choice values become comments. Input is
    commented out, because applying it would switch the monitor to it.
    """
    key = name if BARE_KEY.fullmatch(name) else json.dumps(name)
    lines = [f"[profiles.{key}]"]
    for feature_name, reading in status.items():
        feature = features.features[feature_name]
        if reading is None or reading.value is None:
            lines.append(f"# {feature_name}: unreadable")
            continue
        if feature.kind != "choice":
            setting = f"{feature_name} = {reading.value}"
        elif label := name_for(feature.values, reading.value):
            setting = f"{feature_name} = {json.dumps(label)}"
        else:
            lines.append(f"# {feature_name}: 0x{reading.value:02x} has no name")
            continue
        if feature_name in LAST:
            lines.append(
                "# Applying input switches the monitor to it. Uncomment to keep it."
            )
            lines.append(f"# {setting}")
        else:
            lines.append(setting)
    return "\n".join(lines) + "\n"
