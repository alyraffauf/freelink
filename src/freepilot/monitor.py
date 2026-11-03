"""Monitor operations, independent of how freepilot talks to the monitor."""

import time
from dataclasses import dataclass

from freepilot.features import (
    FEATURES,
    INPUT_SOURCES,
    MUTE_STATES,
    PICTURE_MODES,
    WRITE_DELAYS,
)
lazy from freepilot.vcp import Reading, Transport

# The features status reads, in the order it shows them.
STATUS_FEATURES = ("picture-mode", "input", "brightness", "contrast", "volume", "mute")


@dataclass(frozen=True, slots=True)
class Monitor:
    """A BenQ RD series monitor reached through a transport."""

    transport: Transport

    def read(self, *codes: int) -> dict[int, Reading]:
        """Read raw VCP codes."""
        with self.transport.session():
            return self.transport.get(*codes)

    def write(self, code: int, value: int) -> None:
        """Write a raw VCP code, then wait as long as Display Pilot 2 does.

        The wait happens inside the session, so nothing else uses the bus
        while the monitor settles.
        """
        with self.transport.session():
            self.transport.set(code, value)
            time.sleep(WRITE_DELAYS.get(code, 0) / 1000)

    def status(self) -> dict[str, Reading | None]:
        """Read the STATUS_FEATURES in one request, keyed by feature name.

        Readings stay raw. Naming their values is left to whoever shows them.
        """
        readings = self.read(*(FEATURES[name].code for name in STATUS_FEATURES))
        return {name: readings.get(FEATURES[name].code) for name in STATUS_FEATURES}

    def set_picture_mode(self, name: str) -> None:
        """Switch to a named picture mode."""
        self.write(FEATURES["picture-mode"].code, PICTURE_MODES[name])

    def set_input(self, name: str) -> None:
        """Switch to a named input source."""
        self.write(FEATURES["input"].code, INPUT_SOURCES[name])

    def set_level(self, feature: str, value: int) -> None:
        """Set a 0-100 level such as brightness, contrast, or volume."""
        self.write(FEATURES[feature].code, value)

    def set_muted(self, *, muted: bool) -> None:
        """Mute or unmute the speakers."""
        self.write(FEATURES["mute"].code, MUTE_STATES["on" if muted else "off"])
