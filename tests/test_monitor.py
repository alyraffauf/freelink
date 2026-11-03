"""Tests for monitor operations against a fake transport."""

lazy from collections.abc import Callable

import pytest
from conftest import FakeTransport

from freepilot import monitor
from freepilot.monitor import Monitor
from freepilot.vcp import Reading


def test_status_keeps_raw_readings_by_name() -> None:
    """Status returns every status feature's raw reading, None when missing."""
    transport = FakeTransport(
        {
            0xDC: Reading(0xDC, 0x99),
            0x10: Reading(0x10, 42, 100),
            0x8D: Reading(0x8D, 7),
        }
    )
    assert Monitor(transport).status() == {
        "picture-mode": Reading(0xDC, 0x99),
        "input": None,
        "brightness": Reading(0x10, 42, 100),
        "contrast": None,
        "volume": None,
        "mute": Reading(0x8D, 7),
    }


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


def test_write_settles_inside_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The post-write wait happens before the session closes."""
    transport = FakeTransport()
    monkeypatch.setattr(monitor.time, "sleep", lambda _: transport.log.append("wait"))
    Monitor(transport).set_picture_mode("srgb")
    assert transport.log == ["open", "set 0xdc", "wait", "close"]
