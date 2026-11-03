"""Tests for running ddcutil and parsing its output."""

import pytest
from conftest import TERSE, FakeRun

from freepilot import ddcutil
from freepilot.ddcutil import Ddcutil, DdcutilError
from freepilot.vcp import Reading


def test_parse_terse_handles_c_snc_cnc_and_errors() -> None:
    """Continuous (C), non-continuous (SNC and CNC), and ERR lines parse."""
    output = TERSE + "VCP 14 CNC x00 x00 x01 x05\nnot a reading\n"
    readings = ddcutil.parse_terse(output)
    assert readings[0x10] == Reading(0x10, 42, 100)
    assert readings[0xDC] == Reading(0xDC, 0x31)
    assert readings[0x14] == Reading(0x14, 0x0105)
    assert readings[0xE4] == Reading(0xE4, None)
    # Seven readings in TERSE plus the CNC line; the last line is ignored.
    assert len(readings) == 8


def test_parse_terse_rejects_bad_numbers() -> None:
    """A reading-shaped line with bad numbers raises DdcutilError, quoting it."""
    with pytest.raises(DdcutilError, match="'VCP 10 C abc 100'"):
        ddcutil.parse_terse("VCP 10 C abc 100\n")


def test_get_and_set_build_ddcutil_commands(fake_run: FakeRun) -> None:
    """Codes go to ddcutil as 0x hex, after the display selector."""
    transport = Ddcutil(("--bus", "7"))
    transport.get(0x10, 0xDC)
    transport.set(0x60, 17)
    assert fake_run.calls == [
        ["ddcutil", "--bus", "7", "getvcp", "--terse", "0x10", "0xdc"],
        ["ddcutil", "--bus", "7", "setvcp", "0x60", "17"],
    ]


def test_failed_run_raises_with_ddcutil_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero exit raises DdcutilError with ddcutil's stderr."""
    monkeypatch.setattr(ddcutil.subprocess, "run", FakeRun(returncode=1))
    with pytest.raises(DdcutilError, match="Display not found"):
        Ddcutil().get(0x10)


def test_missing_ddcutil_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ddcutil binary raises DdcutilError."""

    def missing(*_: object, **__: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(ddcutil.subprocess, "run", missing)
    with pytest.raises(DdcutilError, match="not installed"):
        Ddcutil().get(0x10)


def test_capabilities_reads_the_terse_line(fake_run: FakeRun) -> None:
    """The string comes from ddcutil's 'Unparsed capabilities string:' line."""
    fake_run.capabilities = "Unparsed capabilities string: (prot(monitor)vcp(10 12))\n"
    assert Ddcutil().capabilities() == "(prot(monitor)vcp(10 12))"
    assert fake_run.calls == [["ddcutil", "capabilities", "--terse"]]


def test_capabilities_without_the_line_is_an_error(fake_run: FakeRun) -> None:
    """Output without a capability string is a DdcutilError."""
    fake_run.capabilities = "Display not found\n"
    with pytest.raises(DdcutilError, match="no capability string"):
        Ddcutil().capabilities()
