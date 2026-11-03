"""End-to-end tests for the freepilot command line."""

import argparse
import json
lazy from pathlib import Path

import pytest
from conftest import FakeDevice, FakeRun, Log, make_connector, make_edid

from freepilot import cli, ddcutil, i2c


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


def test_monitor_resolves_to_a_ddcutil_bus(fake_run: FakeRun) -> None:
    """--monitor finds the bus itself and passes it to ddcutil."""
    cli.main(["--monitor", "rd280u", "brightness", "40"])
    assert fake_run.calls == [["ddcutil", "--bus", "4", "setvcp", "0x10", "40"]]


def test_monitor_uses_config_aliases(sysfs: Path, fake_run: FakeRun) -> None:
    """A config alias names a monitor by serial."""
    (sysfs / "config.toml").write_text('[monitors.desk]\nserial = "ABC123"\n')
    cli.main(["--monitor", "desk", "volume", "5"])
    assert fake_run.calls[0][:3] == ["ddcutil", "--bus", "4"]


@pytest.mark.usefixtures("fake_run")
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


@pytest.fixture
def fake_device(monkeypatch: pytest.MonkeyPatch) -> FakeDevice:
    """Replace /dev/i2c-N with a device that logs what it is sent."""
    log: Log = []
    device = FakeDevice(log, [bytes.fromhex("6e 88 02 00 10 00 00 64 00 2a ea")])

    def open_device(bus: int) -> FakeDevice:
        log.append(("open", bus))
        return device

    monkeypatch.setattr(i2c.LinuxDevice, "open", open_device)
    return device


def test_i2c_transport_writes_to_the_selected_bus(fake_device: FakeDevice) -> None:
    """--transport i2c opens the monitor's bus and sends the Set request."""
    cli.main(["--transport", "i2c", "--monitor", "DP-1", "brightness", "40"])
    assert ("open", 4) in fake_device.log
    assert ("write", "51 84 03 10 00 28 80") in fake_device.log


def test_i2c_transport_defaults_to_the_only_monitor(
    fake_device: FakeDevice, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a selector, the only connected monitor with a bus is used."""
    cli.main(["--transport", "i2c", "get", "brightness"])
    assert ("open", 4) in fake_device.log
    assert capsys.readouterr().out.split() == ["brightness", "42/100"]


def test_i2c_transport_refuses_several_monitors(
    sysfs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With two monitors and no selector, the i2c transport asks for one."""
    make_connector(sysfs / "drm", "card1-DP-2", ddc_bus=5)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--transport", "i2c", "status"])
    assert exit_info.value.code == 1
    assert "pick one with --monitor" in capsys.readouterr().err


def test_i2c_transport_rejects_display_numbers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--display is ddcutil's numbering, so it is a usage error with i2c."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--transport", "i2c", "--display", "1", "status"])
    assert exit_info.value.code == 2
    assert "--display is ddcutil's numbering" in capsys.readouterr().err


def test_capabilities_names_codes_and_lists_unlisted_features(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Capabilities shows each listed code with freepilot's names for it."""
    cli.main(["capabilities"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["model", "RD280U"]
    assert (
        "0x60  input                    0x0f displayport, 0x11 hdmi, 0x13 usb-c"
        in lines
    )
    assert "0x8d  mute                     0x01 on, 0x02 off" in lines
    assert lines[-1].startswith("not listed by the monitor: ")
    assert "kvm" in lines[-1]
    assert "brightness" not in lines[-1]
    assert fake_run.calls == [["ddcutil", "capabilities", "--terse"]]


def test_capabilities_json(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Capabilities --json carries the parsed codes and the raw string."""
    cli.main(["capabilities", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["model"] == "RD280U"
    assert {
        "code": 0x60,
        "name": "input",
        "values": [0x0F, 0x11, 0x13],
        "malformed": False,
    } in data["vcp"]
    assert "kvm" in data["unlisted"]
    assert fake_run.calls[0][1] == "capabilities"


@pytest.mark.parametrize(
    "argv",
    [["input", "hdmi"], ["brightness", "40"], ["mode", "coding-dark"]],
)
def test_strict_allows_listed_writes(fake_run: FakeRun, argv: list[str]) -> None:
    """--strict fetches capabilities once, then sends writes they list."""
    cli.main(["--strict", *argv])
    assert [call[1] for call in fake_run.calls] == ["capabilities", "setvcp"]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["mode", "coding-paper"], "does not list value 0x3a for VCP 0xdc"),
        (["set", "kvm", "1"], "does not list VCP 0xe4"),
    ],
)
def test_strict_refuses_unlisted_writes(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    """--strict refuses unlisted codes and choice values without writing."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--strict", *argv])
    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err
    assert all(call[1] != "setvcp" for call in fake_run.calls)


def test_writes_skip_capabilities_without_strict(fake_run: FakeRun) -> None:
    """Without --strict, a write is one ddcutil call."""
    cli.main(["set", "kvm", "1"])
    assert [call[1] for call in fake_run.calls] == ["setvcp"]


def write_dell(sysfs: Path) -> None:
    """Replace the fake BenQ with a Dell monitor on the same bus."""
    root = sysfs / "drm"
    connector = root / "card1-DP-1"
    (connector / "edid").write_bytes(
        make_edid(manufacturer=b"\x10\xac", texts={0xFC: b"DELL U2723QE\n"})
    )


def test_other_monitors_get_the_standard_set(
    sysfs: Path, fake_run: FakeRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-BenQ monitor's status skips picture mode and uses MCCS names."""
    write_dell(sysfs)
    fake_run.output = "VCP 60 SNC x11\nVCP 10 C 42 100\n"
    cli.main(["status"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["input", "hdmi"]
    assert not any(line.startswith("picture-mode") for line in lines)
    assert "0xdc" not in fake_run.calls[0]


@pytest.mark.usefixtures("fake_run")
@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["mode", "coding-dark"], "picture-mode isn't available for Standard MCCS"),
        (["input", "usb-c"], "usb-c isn't a known input for Standard MCCS"),
    ],
)
def test_benq_names_are_refused_on_other_monitors(
    sysfs: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    """BenQ picture modes and input values aren't sent to other monitors."""
    write_dell(sysfs)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err


def test_model_overrides_identification(sysfs: Path, fake_run: FakeRun) -> None:
    """--model benq-rd uses the BenQ set whatever the EDID says."""
    write_dell(sysfs)
    cli.main(["--model", "benq-rd", "input", "usb-c"])
    assert fake_run.calls == [["ddcutil", "setvcp", "0x60", "19"]]


def test_alias_model_overrides_identification(sysfs: Path, fake_run: FakeRun) -> None:
    """A config alias can force a feature set too."""
    write_dell(sysfs)
    (sysfs / "config.toml").write_text(
        '[monitors.desk]\nconnector = "DP-1"\nmodel = "benq-rd"\n'
    )
    cli.main(["--monitor", "desk", "mode", "srgb"])
    assert fake_run.calls == [["ddcutil", "--bus", "4", "setvcp", "0xdc", "10"]]


def test_unidentified_monitors_get_the_standard_set(
    sysfs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no monitor to identify, codes shows the standard set."""
    write_dell(sysfs)
    cli.main(["codes"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Standard MCCS controls (mccs)"
    assert len(lines) == 7


def test_codes_shows_the_benq_set_for_benq_monitors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fake BenQ RD280U is identified, so codes shows the BenQ set."""
    cli.main(["codes"])
    assert capsys.readouterr().out.splitlines()[0] == "BenQ RD series (benq-rd)"
