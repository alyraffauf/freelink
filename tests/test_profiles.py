"""Tests for planning, applying, and saving profiles."""

import tomllib

import pytest
from conftest import FakeTransport

from freepilot import profiles
from freepilot.capabilities import CapabilityError
from freepilot.config import Profile, parse_profile
from freepilot.features import BENQ_RD, MCCS
from freepilot.monitor import Monitor, UnsupportedError
from freepilot.vcp import Reading

EVERYTHING = Profile(
    settings=frozendict(
        {
            "input": "hdmi",
            "mute": "off",
            "brightness": 40,
            "picture-mode": "coding-dark",
            "contrast": 50,
        }
    ),
    vcp=frozendict({0xD1: 2, 0x81: 1}),
)


def test_plan_orders_picture_mode_first_and_input_last() -> None:
    """Picture mode, levels, mute, raw codes ascending, then input."""
    steps = profiles.plan(EVERYTHING, Monitor(FakeTransport()))
    assert [step.label for step in steps] == [
        "picture-mode coding-dark",
        "brightness 40",
        "contrast 50",
        "mute off",
        "vcp 0x81 = 1",
        "vcp 0xd1 = 2",
        "input hdmi",
    ]
    assert (steps[0].code, steps[0].value) == (0xDC, 0x30)


def test_plan_checks_names_against_the_monitor() -> None:
    """A BenQ picture mode on a standard monitor fails before anything is sent."""
    with pytest.raises(UnsupportedError, match="picture-mode"):
        profiles.plan(EVERYTHING, Monitor(FakeTransport(), MCCS))


def test_apply_writes_everything_in_one_session() -> None:
    """All writes share one session, in plan order."""
    transport = FakeTransport()
    monitor = Monitor(transport)
    profiles.apply(monitor, profiles.plan(EVERYTHING, monitor))
    assert transport.log[0] == "open"
    assert transport.log[-1] == "close"
    assert transport.writes[0] == (0xDC, 0x30)
    assert transport.writes[-1] == (0x60, 0x11)


class FailingTransport(FakeTransport):
    """Fail the write to one code."""

    def __init__(self, failing_code: int) -> None:
        """Remember which code fails."""
        super().__init__()
        self.failing_code = failing_code

    def set(self, code: int, value: int) -> None:
        """Raise for the failing code; record the rest."""
        if code == self.failing_code:
            message = "no DDC/CI answer"
            raise CapabilityError(message)
        super().set(code, value)


def test_failure_says_what_was_sent_and_what_was_not() -> None:
    """A failure stops at once and reports sent, failed, and skipped writes."""
    transport = FailingTransport(0x8D)
    monitor = Monitor(transport)
    with pytest.raises(profiles.ProfileError) as error:
        profiles.apply(monitor, profiles.plan(EVERYTHING, monitor))
    message = str(error.value)
    assert message.startswith("mute off failed and may or may not have applied")
    assert "sent: picture-mode coding-dark, brightness 40, contrast 50" in message
    assert "not attempted: vcp 0x81 = 1, vcp 0xd1 = 2, input hdmi" in message
    assert (0x60, 0x11) not in transport.writes


def test_strict_checks_every_step_before_the_first_write() -> None:
    """A refused step means no writes at all."""
    transport = FakeTransport()

    def refuse_input(code: int, _: int) -> None:
        if code == 0x60:
            message = "the monitor does not list VCP 0x60"
            raise CapabilityError(message)

    monitor = Monitor(transport, check=refuse_input)
    with pytest.raises(CapabilityError):
        profiles.apply(monitor, profiles.plan(EVERYTHING, monitor))
    assert transport.writes == []


def test_save_round_trips_through_toml() -> None:
    """Saved output parses as TOML and as a profile, minus unreadable values."""
    status = {
        "picture-mode": Reading(0xDC, 0x30),
        "input": Reading(0x60, 0x13),
        "brightness": Reading(0x10, 40, 100),
        "contrast": None,
        "volume": Reading(0x62, 10, 100),
        "mute": Reading(0x8D, 0x07),
    }
    text = profiles.save("evening work", status, BENQ_RD)
    assert text.splitlines()[0] == '[profiles."evening work"]'
    assert "# contrast: unreadable" in text
    assert "# mute: 0x07 has no name" in text
    assert '# input = "usb-c"' in text
    table = tomllib.loads(text)["profiles"]["evening work"]
    assert table == {"picture-mode": "coding-dark", "brightness": 40, "volume": 10}
    assert parse_profile(table, "saved").settings == table
