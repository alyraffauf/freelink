"""End-to-end tests for the freepilot command line."""

import argparse

import pytest
from conftest import FakeRun

from freepilot import cli, ddcutil


@pytest.mark.parametrize(("text", "code"), [("brightness", 0x10), ("0xdc", 0xDC)])
def test_resolve_code_accepts_names_and_numbers(text: str, code: int) -> None:
    """Features resolve by name or by number."""
    assert cli.resolve_code(text) == code


def test_resolve_code_rejects_unknown_names() -> None:
    """An unknown name is an argument error that points to 'codes'."""
    with pytest.raises(argparse.ArgumentTypeError, match="freepilot codes"):
        cli.resolve_code("sparkle")


@pytest.mark.parametrize("text", ["-1", "101"])
def test_percent_rejects_out_of_range(text: str) -> None:
    """Levels outside 0-100 are argument errors."""
    with pytest.raises(argparse.ArgumentTypeError):
        cli.percent(text)


def test_status_prints_names_and_levels(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status shows the picture mode and input by name, and levels out of max."""
    cli.main(["status"])
    assert capsys.readouterr().out.splitlines() == [
        "picture-mode   coding-light",
        "input          usb-c",
        "brightness     42/100",
        "contrast       50/100",
        "volume         20/100",
        "mute           off",
    ]
    assert fake_run.calls[0][:2] == ["ddcutil", "getvcp"]


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
def test_commands_run_the_expected_ddcutil_write(
    fake_run: FakeRun, argv: list[str], expected: list[str]
) -> None:
    """Each command writes the VCP code and value Display Pilot 2 uses."""
    cli.main(argv)
    assert fake_run.calls == [["ddcutil", *expected]]


def test_bus_selects_the_display(fake_run: FakeRun) -> None:
    """--bus passes through to ddcutil."""
    cli.main(["--bus", "7", "volume", "20"])
    assert fake_run.calls == [["ddcutil", "--bus", "7", "setvcp", "0x62", "20"]]


def test_get_prints_in_request_order(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Readings print in the order asked for, including unreadable ones."""
    cli.main(["get", "kvm", "brightness"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["kvm", "unreadable"]
    assert lines[1].split() == ["brightness", "42/100"]
    assert fake_run.calls[0][-2:] == ["0xe4", "0x10"]


@pytest.mark.parametrize(
    ("fake", "message"),
    [
        (FakeRun(returncode=1), "freepilot: Display not found"),
        (FakeRun("VCP 10 C abc 100\n"), "unexpected ddcutil output"),
    ],
)
def test_ddcutil_problems_exit_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake: FakeRun,
    message: str,
) -> None:
    """Failures and bad output from ddcutil exit 1 with a message, no traceback."""
    monkeypatch.setattr(ddcutil.subprocess, "run", fake)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["status"])
    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err


def test_unrelated_errors_keep_their_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bugs outside ddcutil are not reported as monitor errors."""

    def broken(*_: object, **__: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(cli, "show_status", broken)
    with pytest.raises(RuntimeError):
        cli.main(["status"])
