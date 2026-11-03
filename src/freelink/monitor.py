"""Monitor operations, independent of how freelink talks to the monitor."""

import time
from dataclasses import dataclass
from typing import Protocol

from freelink.ddcutil import Reading
from freelink.features import (
    FEATURES,
    INPUT_SOURCES,
    MUTED,
    PICTURE_MODES,
    UNMUTED,
    WRITE_DELAYS,
    name_for,
)


class Transport(Protocol):
    """Reads and writes raw VCP codes. freelink.ddcutil.Ddcutil is one."""

    def get(self, *codes: int) -> dict[int, Reading]:
        """Read one or more VCP codes."""
        ...

    def set(self, code: int, value: int) -> None:
        """Write one VCP code."""
        ...


@dataclass(frozen=True)
class Status:
    """The common settings. None means the monitor did not answer.

    picture_mode and input_source hold a name, or the raw value in hex when
    freelink does not know it.
    """

    picture_mode: str | None
    input_source: str | None
    brightness: Reading | None
    contrast: Reading | None
    volume: Reading | None
    muted: bool | None


def decode_choice(table: dict[str, int], reading: Reading | None) -> str | None:
    """Name a reading's value from a name table, or show it in hex."""
    if reading is None or reading.value is None:
        return None
    return name_for(table, reading.value) or f"0x{reading.value:02x}"


@dataclass(frozen=True)
class Monitor:
    """A BenQ RD series monitor reached through a transport."""

    transport: Transport

    def read(self, *codes: int) -> dict[int, Reading]:
        """Read raw VCP codes."""
        return self.transport.get(*codes)

    def write(self, code: int, value: int) -> None:
        """Write a raw VCP code, then wait as long as Display Pilot 2 does."""
        self.transport.set(code, value)
        time.sleep(WRITE_DELAYS.get(code, 0) / 1000)

    def status(self) -> Status:
        """Read picture mode, input, levels, and mute in one request."""
        names = ("picture-mode", "input", "brightness", "contrast", "volume", "mute")
        readings = self.read(*(FEATURES[name].code for name in names))

        def reading(name: str) -> Reading | None:
            return readings.get(FEATURES[name].code)

        mute = reading("mute")
        return Status(
            picture_mode=decode_choice(PICTURE_MODES, reading("picture-mode")),
            input_source=decode_choice(INPUT_SOURCES, reading("input")),
            brightness=reading("brightness"),
            contrast=reading("contrast"),
            volume=reading("volume"),
            muted={MUTED: True, UNMUTED: False}.get(mute.value) if mute else None,
        )

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
        self.write(FEATURES["mute"].code, MUTED if muted else UNMUTED)
