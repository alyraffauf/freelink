"""Tests for reading config.toml."""

from pathlib import Path

import pytest

from freepilot.config import Alias, Config, ConfigError, config_path, load_config


def test_config_path_prefers_freepilot_config() -> None:
    """$FREEPILOT_CONFIG wins, then $XDG_CONFIG_HOME."""
    assert config_path({"FREEPILOT_CONFIG": "/a.toml"}) == Path("/a.toml")
    assert config_path({"XDG_CONFIG_HOME": "/x"}) == Path("/x/freepilot/config.toml")


def test_missing_config_is_empty(tmp_path: Path) -> None:
    """No file means no aliases, not an error."""
    assert load_config(tmp_path / "missing.toml") == Config()


def test_monitor_aliases_load(tmp_path: Path) -> None:
    """[monitors.NAME] tables become aliases."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[monitors.desk]\nserial = "ABC123"\n\n[monitors.tv]\nconnector = "HDMI-A-1"\n'
    )
    assert load_config(path).monitors == {
        "desk": Alias(serial="ABC123"),
        "tv": Alias(connector="HDMI-A-1"),
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("monitors = 1", r"\[monitors\] must be a table"),
        ("[monitors]\ndesk = 1", r"\[monitors.desk\] must be a table"),
        ("[monitors.desk]\nbus = 7", "unknown keys: bus"),
        ("[monitors.desk]\nserial = 7", "serial must be a string"),
        ("[monitors.desk]", "needs serial or connector"),
        ('[monitors.desk]\nmodel = "benq-rd"', "needs serial or connector"),
        ('[monitors.desk]\nserial = "A"\nmodel = "acme"', "model must be one of"),
        ("[monitors", "config.toml"),
    ],
)
def test_bad_config_names_the_problem(tmp_path: Path, text: str, message: str) -> None:
    """Errors name the file, the table, and the key."""
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_profiles_load(tmp_path: Path) -> None:
    """[profiles.NAME] tables become profiles with named and raw settings."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[profiles.coding]\nmonitor = "desk"\npicture-mode = "coding-dark"\n'
        'brightness = 40\n\n[profiles.coding.vcp]\n"0xd1" = 2\n'
    )
    profile = load_config(path).profiles["coding"]
    assert profile.monitor == "desk"
    assert profile.settings == {"picture-mode": "coding-dark", "brightness": 40}
    assert profile.vcp == {0xD1: 2}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[profiles.p]\nsparkle = 1", "unknown key: sparkle"),
        ("[profiles.p]\nbrightness = true", "brightness must be an integer"),
        ("[profiles.p]\nbrightness = 101", "brightness is outside 0-100"),
        ("[profiles.p]\ninput = 17", "input must be a string"),
        ("[profiles.p]\nmonitor = 1\nbrightness = 1", "monitor must be a string"),
        ("[profiles.p]", "sets nothing"),
        ('[profiles.p.vcp]\n"0xdc" = 1', "can't set 0xdc"),
        ('[profiles.p.vcp]\n"0x60" = 1', "use the input key"),
        ('[profiles.p.vcp]\n"kvm" = 1', "is not a number"),
        ('[profiles.p.vcp]\n"0x100" = 1', "outside 0-0xff"),
        ('[profiles.p.vcp]\n"0xd1" = 70000', "outside 0-65535"),
        ('[profiles.p]\nbrightness = 4\n[profiles.p.vcp]\n"0x10" = 5', "both by name"),
    ],
)
def test_bad_profiles_are_refused_before_anything_runs(
    tmp_path: Path, text: str, message: str
) -> None:
    """Profiles are checked when the config loads."""
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path)
