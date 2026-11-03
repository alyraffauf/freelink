"""Tests for capability string parsing.

The quirky strings come from real monitors, as collected in ddcutil's
parse_capabilities.c.
"""

import pytest

from freepilot.capabilities import (
    Capabilities,
    VcpEntry,
    parse_capabilities,
    write_problem,
)

# LG 25UM65: codes packed without spaces, and an odd-length cmds entry.
LG_25UM65 = (
    "(prot(monitor)type(LED)model(25UM65)cmds(01 02 03 0C E33 F3)"
    "vcp(0203(10 00)0405080B0C101214(05 07 08 0B) 16181A5260(3033 04)6C6E70"
    "87ACAEB6C0C6C8C9D6(01 04)DFE4E5E6E7E8E9EAEBED(00 10 20 40)EE(00 01)"
    "FE(01 02 03)FF)mswhql(1)mccs_ver(2.1))"
)
# Asus PB287: model without parentheses.
ASUS_PB287 = (
    "(prot(monitor) type(LCD)model LCDPB287 cmds(01 02 03 07 0C F3) "
    "vcp(02 04 05 08 0B 0C 10 12 14(05 06 08 0B) 16 18 1A 60(11 12 0F) "
    "62 6C 6E 70 8D(01 02) A8 AC AE B6 C6 C8 C9 D6(01 04) DF) "
    "mccs_ver(2.1)asset_eep(32)mpu(01)mswhql(1))"
)


def test_parses_a_well_formed_string() -> None:
    """Model, type, version, commands, and value lists come through."""
    caps = parse_capabilities(ASUS_PB287)
    assert caps.display_type == "LCD"
    assert caps.mccs_version == "2.1"
    assert caps.commands == (0x01, 0x02, 0x03, 0x07, 0x0C, 0xF3)
    assert caps.vcp[0x60] == VcpEntry((0x11, 0x12, 0x0F))
    assert caps.vcp[0x10] == VcpEntry()
    assert caps.other["asset_eep"] == "32"


def test_model_without_parentheses_is_missing_not_fatal() -> None:
    """A model freepilot can't find leaves model None and parses the rest."""
    caps = parse_capabilities(ASUS_PB287)
    assert caps.model is None
    assert 0x8D in caps.vcp


def test_packed_codes_and_bad_cmds() -> None:
    """Codes packed without spaces parse; an unreadable cmds list is empty."""
    caps = parse_capabilities(LG_25UM65)
    assert caps.model == "25UM65"
    assert caps.commands == ()
    assert caps.vcp[0x02] == VcpEntry()
    assert caps.vcp[0x03] == VcpEntry((0x10, 0x00))
    assert caps.vcp[0x14] == VcpEntry((0x05, 0x07, 0x08, 0x0B))
    assert caps.vcp[0x60] == VcpEntry((0x30, 0x33, 0x04))
    assert caps.vcp[0xED] == VcpEntry((0x00, 0x10, 0x20, 0x40))
    assert {0x04, 0x05, 0x08, 0x0B, 0x0C, 0x10, 0x12, 0xFF} <= caps.vcp.keys()


def test_nested_value_lists_are_marked_malformed() -> None:
    """A value list with groups inside is kept as malformed, not misread."""
    caps = parse_capabilities("vcp(10 F7(01(01) 02 09(01 02)) 12)")
    assert caps.vcp[0xF7] == VcpEntry(None, malformed=True)
    assert {0x10, 0x12} <= caps.vcp.keys()


@pytest.mark.parametrize(
    "raw",
    [
        "prot(monitor)vcp(10 12)",  # no outer parentheses
        "(prot(monitor)vcp(10 12)) junk after",
        "(prot(monitor)vcp(10 12",  # never closed
        "(prot(monitor)vcp(10)vcp(12))",  # vcp split in two
        "(vcp( 10\n 12 ))",
    ],
)
def test_tolerates_common_damage(raw: str) -> None:
    """Missing or extra parentheses, split groups, and whitespace still parse."""
    assert {0x10, 0x12} <= parse_capabilities(raw).vcp.keys()


@pytest.mark.parametrize(
    ("code", "value", "check_value", "problem"),
    [
        (0x10, 40, False, None),
        (0x60, 0x11, True, None),
        (0x60, 0x13, True, "the monitor does not list value 0x13 for VCP 0x60"),
        (0x60, 0x13, False, None),
        (0xE4, 1, False, "the monitor does not list VCP 0xe4"),
        (0xF7, 9, True, None),  # an unreadable list proves nothing
    ],
)
def test_write_problem(
    code: int, value: int, *, check_value: bool, problem: str | None
) -> None:
    """Unlisted codes are problems; values only for choices with a readable list."""
    caps = Capabilities(
        raw="",
        vcp=frozendict(
            {
                0x10: VcpEntry(),
                0x60: VcpEntry((0x0F, 0x11)),
                0xF7: VcpEntry(None, malformed=True),
            }
        ),
    )
    assert write_problem(caps, code, value, check_value=check_value) == problem
