"""Tests for the freelink command line."""

import argparse
import subprocess

import pytest

from freelink import cli

TERSE = """\
VCP dc SNC x31
VCP 60 SNC x13
VCP 10 C 42 100
VCP 12 C 50 100
VCP 62 C 20 100
VCP 8d SNC x02
VCP e4 ERR
"""


class FakeDdcutil:
    """Record ddcutil calls and answer getvcp with canned output."""

    def __init__(self, output: str = TERSE, returncode: int = 0) -> None:
        """Store the reply every call returns."""
        self.output = output
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(
        self, command: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        """Stand in for subprocess.run."""
        self.calls.append(command)
        stdout = self.output if "getvcp" in command else ""
        stderr = "" if self.returncode == 0 else "Display not found"
        return subprocess.CompletedProcess(command, self.returncode, stdout, stderr)


@pytest.fixture
def ddcutil(monkeypatch: pytest.MonkeyPatch) -> FakeDdcutil:
    """Replace ddcutil and skip write delays."""
    fake = FakeDdcutil()
    monkeypatch.setattr(cli.subprocess, "run", fake)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    return fake


def test_parse_terse_reads_every_kind() -> None:
    """Continuous, simple, complex, and failed readings all parse."""
    readings = cli.parse_terse(TERSE + "VCP 14 CNC x00 x00 x01 x05\nnoise\n")
    assert readings[0x10] == cli.Reading(0x10, 42, 100)
    assert readings[0xDC] == cli.Reading(0xDC, 0x31)
    assert readings[0x14] == cli.Reading(0x14, 0x0105)
    assert readings[0xE4] == cli.Reading(0xE4, None)
    assert len(readings) == 8


@pytest.mark.parametrize(("text", "code"), [("brightness", 0x10), ("0xdc", 0xDC)])
def test_resolve_code_accepts_names_and_numbers(text: str, code: int) -> None:
    """Features resolve by name or by number."""
    assert cli.resolve_code(text) == code


def test_resolve_code_rejects_unknown_names() -> None:
    """An unknown name is an argument error."""
    with pytest.raises(argparse.ArgumentTypeError, match="unknown feature"):
        cli.resolve_code("sparkle")


@pytest.mark.parametrize("text", ["-1", "101"])
def test_percent_rejects_out_of_range(text: str) -> None:
    """Levels outside 0-100 are argument errors."""
    with pytest.raises(argparse.ArgumentTypeError):
        cli.percent(text)


def test_status_names_mode_and_input(
    ddcutil: FakeDdcutil, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status shows named picture mode and input, and levels out of their max."""
    cli.main(["status"])
    output = capsys.readouterr().out
    assert "coding-light" in output
    assert "usb-c" in output
    assert "42/100" in output
    assert "mute           off" in output
    assert ddcutil.calls[0][:2] == ["ddcutil", "getvcp"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["mode", "coding-dark"], ["setvcp", "0xdc", "48"]),
        (["input", "hdmi"], ["setvcp", "0x60", "17"]),
        (["brightness", "40"], ["setvcp", "0x10", "40"]),
        (["mute", "on"], ["setvcp", "0x8d", "1"]),
        (["set", "kvm", "0x2"], ["setvcp", "0xe4", "2"]),
    ],
)
def test_commands_write_expected_values(
    ddcutil: FakeDdcutil, argv: list[str], expected: list[str]
) -> None:
    """Each command writes the VCP code and value Display Pilot 2 uses."""
    cli.main(argv)
    assert ddcutil.calls == [["ddcutil", *expected]]


def test_bus_selects_the_display(ddcutil: FakeDdcutil) -> None:
    """--bus passes through to ddcutil."""
    cli.main(["--bus", "7", "volume", "20"])
    assert ddcutil.calls == [["ddcutil", "--bus", "7", "setvcp", "0x62", "20"]]


def test_get_prints_in_request_order(
    ddcutil: FakeDdcutil, capsys: pytest.CaptureFixture[str]
) -> None:
    """Readings print in the order asked for, including unreadable ones."""
    cli.main(["get", "kvm", "brightness"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["kvm", "unreadable"]
    assert lines[1].split() == ["brightness", "42/100"]
    assert ddcutil.calls[0][-2:] == ["0xe4", "0x10"]


def test_ddcutil_failure_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failing ddcutil exits 1 with its message."""
    monkeypatch.setattr(cli.subprocess, "run", FakeDdcutil(returncode=1))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["status"])
    assert exit_info.value.code == 1
    assert "freelink: Display not found" in capsys.readouterr().err


def test_malformed_output_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Output in a known shape with bad numbers exits 1 and quotes the line."""
    monkeypatch.setattr(cli.subprocess, "run", FakeDdcutil("VCP 10 C abc 100\n"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["status"])
    assert exit_info.value.code == 1
    assert "unexpected ddcutil output: 'VCP 10 C abc 100'" in capsys.readouterr().err


def test_unrelated_errors_are_not_reported_as_monitor_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bugs outside ddcutil keep their traceback."""

    def broken(*_: object, **__: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(cli, "show_status", broken)
    with pytest.raises(RuntimeError):
        cli.main(["status"])


def test_missing_ddcutil_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing ddcutil exits 1 with a hint."""

    def missing(*_: object, **__: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(cli.subprocess, "run", missing)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["status"])
    assert exit_info.value.code == 1
    assert "ddcutil is not installed" in capsys.readouterr().err
