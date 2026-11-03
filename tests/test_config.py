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
