"""Tests for monitor operations against a fake transport."""

lazy from collections.abc import Callable

import pytest

from freepilot import monitor
from freepilot.ddcutil import Reading
from freepilot.monitor import Monitor, Status


class FakeTransport:
    """Answer reads from a fixed table and record writes."""

    def __init__(self, readings: dict[int, Reading] | None = None) -> None:
        """Store the readings that get returns."""
        self.readings = readings or {}
        self.writes: list[tuple[int, int]] = []

    def get(self, *codes: int) -> dict[int, Reading]:
        """Return the stored readings for the requested codes."""
        return {code: self.readings[code] for code in codes if code in self.readings}

    def set(self, code: int, value: int) -> None:
        """Record the write."""
        self.writes.append((code, value))


def test_status_decodes_names_and_mute() -> None:
    """Status names the picture mode and input and decodes mute."""
    transport = FakeTransport(
        {
            0xDC: Reading(0xDC, 0x31),
            0x60: Reading(0x60, 0x11),
            0x10: Reading(0x10, 42, 100),
            0x8D: Reading(0x8D, 1),
        }
    )
    assert Monitor(transport).status() == Status(
        picture_mode="coding-light",
        input_source="hdmi",
        brightness=Reading(0x10, 42, 100),
        contrast=None,
        volume=None,
        muted=True,
    )


def test_status_shows_unknown_values_in_hex() -> None:
    """A value missing from the name table comes back as hex."""
    transport = FakeTransport({0xDC: Reading(0xDC, 0x99), 0x8D: Reading(0x8D, 7)})
    status = Monitor(transport).status()
    assert status.picture_mode == "0x99"
    assert status.muted is None


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (lambda m: m.set_picture_mode("coding-dark"), (0xDC, 0x30)),
        (lambda m: m.set_input("usb-c"), (0x60, 0x13)),
        (lambda m: m.set_level("volume", 20), (0x62, 20)),
        (lambda m: m.set_muted(muted=False), (0x8D, 2)),
    ],
)
def test_setters_write_display_pilot_values(
    operation: Callable[[Monitor], None], expected: tuple[int, int]
) -> None:
    """Each setter writes the code and value Display Pilot 2 uses."""
    transport = FakeTransport()
    operation(Monitor(transport))
    assert transport.writes == [expected]


def test_write_waits_like_display_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Picture-mode writes wait 500 ms; writes without a delay do not wait."""
    sleeps: list[float] = []
    monkeypatch.setattr(monitor.time, "sleep", sleeps.append)
    target = Monitor(FakeTransport())
    target.set_picture_mode("srgb")
    target.set_level("brightness", 10)
    assert sleeps == [0.5, 0.0]
