"""Tests for EDID parsing, sysfs discovery, and --monitor selection."""

lazy from pathlib import Path

import pytest
from conftest import make_connector, make_edid

from freepilot.config import Alias
from freepilot.displays import (
    Display,
    Edid,
    EdidError,
    SelectionError,
    find_displays,
    parse_edid,
    select_display,
)

NAME, SERIAL = 0xFC, 0xFF
RD280U = make_edid(
    serial_number=0x01020304,
    texts={NAME: b"BenQ RD280U\n ", SERIAL: b"ABC123\n      "},
)


def test_parse_edid_reads_identity_fields() -> None:
    """Manufacturer, product, both serials, and the model name come through."""
    assert parse_edid(RD280U) == Edid(
        manufacturer="BNQ",
        product=0x8034,
        serial_number=0x01020304,
        serial="ABC123",
        model="BenQ RD280U",
    )


def test_parse_edid_treats_zero_and_empty_as_missing() -> None:
    """A zero numeric serial and absent descriptors become None."""
    edid = parse_edid(make_edid(manufacturer=b"\x10\xac"))
    assert edid == Edid(manufacturer="DEL", product=0x8034)


def test_parse_edid_ignores_extension_blocks() -> None:
    """Only the base block is checked; a broken extension doesn't matter."""
    assert parse_edid(RD280U + b"\x02" + b"\xff" * 127).model == "BenQ RD280U"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (RD280U[:100], "100 bytes"),
        (b"\x01" + RD280U[1:], "header"),
        (RD280U[:-1] + bytes([(RD280U[-1] + 1) % 256]), "checksum"),
    ],
)
def test_parse_edid_rejects_bad_blobs(data: bytes, message: str) -> None:
    """Short blobs, wrong headers, and bad checksums are EdidErrors."""
    with pytest.raises(EdidError, match=message):
        parse_edid(data)


def test_find_displays_reads_connected_connectors(tmp_path: Path) -> None:
    """Connected connectors are listed with buses best first; others are skipped."""
    make_connector(tmp_path, "card1-DP-1", edid=RD280U, ddc_bus=4, child_buses=(8,))
    make_connector(tmp_path, "card1-DP-2", status="disconnected", ddc_bus=5)
    make_connector(tmp_path, "card1-HDMI-A-1", child_buses=(9,))
    make_connector(tmp_path, "card1-DP-3", edid=b"\x00" * 128)
    assert find_displays(tmp_path) == [
        Display("card1-DP-1", (4, 8), parse_edid(RD280U)),
        Display("card1-DP-3", (), None),
        Display("card1-HDMI-A-1", (9,), None),
    ]


def test_find_displays_skips_connectors_that_vanish(tmp_path: Path) -> None:
    """A connector without a readable status is skipped, not an error."""
    (tmp_path / "card1-DP-1").mkdir()
    assert find_displays(tmp_path) == []


def display(
    connector: str, serial: str | None = None, model: str | None = None
) -> Display:
    """Build a display with a BenQ EDID."""
    return Display(connector, (7,), Edid("BNQ", 1, serial=serial, model=model))


DESK = display("card1-DP-1", serial="ABC123", model="BenQ RD280U")
SIDE = display("card1-DP-2", serial="XYZ789", model="BenQ RD240Q")
OTHER_GPU = display("card2-DP-1", serial="ABC999", model="DELL U2723QE")
ALL = [DESK, SIDE, OTHER_GPU]


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("desk", SIDE),  # an alias wins over everything else
        ("XYZ789", SIDE),
        ("card2-DP-1", OTHER_GPU),
        ("DP-2", SIDE),
        ("rd280", DESK),
        ("dell", OTHER_GPU),
    ],
)
def test_select_display_follows_rule_order(selector: str, expected: Display) -> None:
    """Each rule picks the expected monitor."""
    aliases = {"desk": Alias(serial="XYZ789")}
    assert select_display(ALL, selector, aliases) == expected


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        ("DP-1", "matches several monitors"),
        ("benq", "matches several monitors"),
        ("nope", "no monitor matches"),
        ("gone", "alias 'gone' is not connected"),
    ],
)
def test_select_display_refuses_ambiguity(selector: str, message: str) -> None:
    """Several matches, no matches, and missing aliases are errors."""
    aliases = {"gone": Alias(serial="NOT-HERE")}
    with pytest.raises(SelectionError, match=message):
        select_display(ALL, selector, aliases)


def test_ambiguous_rule_does_not_fall_through() -> None:
    """A serial that two monitors share is an error, even if a later rule is unique."""
    twins = [display("card1-DP-1", serial="SAME"), display("card1-DP-2", serial="SAME")]
    with pytest.raises(SelectionError, match="several"):
        select_display(twins, "SAME", {})


def test_numeric_serial_matches() -> None:
    """The numeric EDID serial matches as decimal text."""
    numbered = Display("card1-DP-1", (7,), Edid("BNQ", 1, serial_number=4242))
    assert select_display([numbered], "4242", {}) == numbered
