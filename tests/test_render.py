"""Tests for showing readings as text and JSON."""

import pytest

from freepilot import render
from freepilot.features import BENQ_RD
from freepilot.vcp import Reading


@pytest.mark.parametrize(
    ("reading", "shown"),
    [
        (Reading(0x60, 0x13), "usb-c"),
        (Reading(0x60, 0x42), "0x42"),
        (Reading(0x8D, 1), "on"),
        (Reading(0x10, 42, 100), "42/100"),
        (Reading(0x10, 42), "42"),
        (Reading(0xE4, 2, 3), "0x02"),
        (Reading(0x42, 5, 10), "5/10"),
        (Reading(0x42, 5), "0x05"),
        (Reading(0x10, None), "unreadable"),
        (None, "unreadable"),
    ],
)
def test_format_reading_follows_the_feature_kind(
    reading: Reading | None, shown: str
) -> None:
    """Choices show by name, levels as current/max, raw and unknown codes in hex."""
    assert render.format_reading(reading, BENQ_RD) == shown


@pytest.mark.parametrize(
    ("code", "reading", "extra"),
    [
        (0x60, Reading(0x60, 0x13, 0xFF), {"kind": "choice", "label": "usb-c"}),
        (0x60, Reading(0x60, 0x42), {"kind": "choice"}),
        (0x10, Reading(0x10, 42, 100), {"kind": "continuous", "max": 100}),
        (0xE4, Reading(0xE4, 2, 3), {"kind": "raw"}),
        (0x42, Reading(0x42, 5, 10), {"kind": "unknown", "max": 10}),
        (0x42, Reading(0x42, 5), {"kind": "unknown"}),
    ],
)
def test_reading_json_adds_label_and_max_only_where_they_mean_something(
    code: int, reading: Reading, extra: dict[str, object]
) -> None:
    """Choice readings get a label; max only appears where it is meaningful."""
    expected = {
        "code": code,
        "name": BENQ_RD.feature_name(code),
        "value": reading.value,
    }
    assert render.reading_json(code, reading, BENQ_RD) == expected | extra


def test_reading_json_marks_no_answer_as_null() -> None:
    """A code the monitor did not answer has a null value and no extras."""
    assert render.reading_json(0x10, None, BENQ_RD) == {
        "code": 0x10,
        "name": "brightness",
        "kind": "continuous",
        "value": None,
    }
