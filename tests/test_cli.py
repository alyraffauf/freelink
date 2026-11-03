"""End-to-end tests for the freepilot command line."""

import argparse
import json
lazy from pathlib import Path

import pytest
from conftest import FakeRun, make_connector, make_edid

from freepilot import cli, ddcutil, displays


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


@pytest.mark.usefixtures("fake_run")
def test_unrelated_errors_keep_their_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bugs outside ddcutil are not reported as monitor errors."""

    def broken(*_: object, **__: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(cli, "status_output", broken)
    with pytest.raises(RuntimeError):
        cli.main(["status"])


def test_json_works_before_or_after_the_command(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json is accepted in either position and prints one JSON document."""
    cli.main(["--json", "status"])
    before = json.loads(capsys.readouterr().out)
    cli.main(["status", "--json"])
    after = json.loads(capsys.readouterr().out)
    assert before == after
    assert before["input"] == {
        "code": 0x60,
        "name": "input",
        "kind": "choice",
        "value": 0x13,
        "label": "usb-c",
    }
    assert before["brightness"]["max"] == 100
    assert len(fake_run.calls) == 2


def test_json_get_keeps_request_order_and_unreadable_codes(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Get --json lists readings in request order, with null for no answer."""
    cli.main(["--json", "get", "kvm", "brightness", "kvm"])
    readings = json.loads(capsys.readouterr().out)
    assert [reading["name"] for reading in readings] == ["kvm", "brightness", "kvm"]
    assert readings[0]["value"] is None
    assert fake_run.calls[0][-3:] == ["0xe4", "0x10", "0xe4"]


def test_json_errors_go_to_stderr_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With --json, a monitor error is a JSON object on stderr and exit 1."""
    monkeypatch.setattr(ddcutil.subprocess, "run", FakeRun(returncode=1))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["status", "--json"])
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "level": "error",
        "message": "Display not found",
    }


def test_json_codes_lists_kinds_and_values(capsys: pytest.CaptureFixture[str]) -> None:
    """Codes --json describes each feature, including its value names."""
    cli.main(["codes", "--json"])
    features = {
        feature["name"]: feature for feature in json.loads(capsys.readouterr().out)
    }
    assert features["mute"]["values"] == {"on": 1, "off": 2}
    assert features["kvm"]["kind"] == "raw"
    assert features["kvm"]["values_confirmed"] is False


@pytest.fixture
def fake_sysfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point discovery at a fake sysfs with one BenQ on bus 4, and no config."""
    root = tmp_path / "drm"
    edid = make_edid(texts={0xFC: b"BenQ RD280U\n", 0xFF: b"ABC123\n"})
    make_connector(root, "card1-DP-1", edid=edid, ddc_bus=4)
    make_connector(root, "card1-HDMI-A-1")
    monkeypatch.setattr(displays, "DRM_ROOT", root)
    monkeypatch.setenv("FREEPILOT_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


@pytest.mark.usefixtures("fake_sysfs")
def test_list_shows_connected_monitors(capsys: pytest.CaptureFixture[str]) -> None:
    """List shows each monitor's connector, bus, and identity."""
    cli.main(["list"])
    assert capsys.readouterr().out.splitlines() == [
        "card1-DP-1         i2c-4    BNQ BenQ RD280U  serial ABC123",
        "card1-HDMI-A-1     no bus   ??? unknown model",
    ]
    cli.main(["list", "--json"])
    first = json.loads(capsys.readouterr().out)[0]
    assert first["bus"] == 4
    assert first["serial"] == "ABC123"


@pytest.mark.usefixtures("fake_sysfs")
def test_monitor_resolves_to_a_ddcutil_bus(fake_run: FakeRun) -> None:
    """--monitor finds the bus itself and passes it to ddcutil."""
    cli.main(["--monitor", "rd280u", "brightness", "40"])
    assert fake_run.calls == [["ddcutil", "--bus", "4", "setvcp", "0x10", "40"]]


def test_monitor_uses_config_aliases(fake_sysfs: Path, fake_run: FakeRun) -> None:
    """A config alias names a monitor by serial."""
    (fake_sysfs / "config.toml").write_text('[monitors.desk]\nserial = "ABC123"\n')
    cli.main(["--monitor", "desk", "volume", "5"])
    assert fake_run.calls[0][:3] == ["ddcutil", "--bus", "4"]


@pytest.mark.usefixtures("fake_sysfs", "fake_run")
@pytest.mark.parametrize(
    ("selector", "message"),
    [("HDMI-A-1", "has no DDC bus"), ("nope", "no monitor matches")],
)
def test_monitor_problems_exit_cleanly(
    capsys: pytest.CaptureFixture[str], selector: str, message: str
) -> None:
    """Selection failures exit 1 with a message."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--monitor", selector, "status"])
    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err
