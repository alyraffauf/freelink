"""Read freepilot's config.toml."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Mapping

from freepilot.errors import FreepilotError

ALIAS_KEYS = frozenset({"serial", "connector"})


class ConfigError(FreepilotError):
    """config.toml is not valid TOML or has a value freepilot can't use."""


@dataclass(frozen=True, slots=True)
class Alias:
    """A name for one monitor. A monitor matches when every given key does."""

    serial: str | None = None
    connector: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    """Everything freepilot reads from config.toml."""

    monitors: frozendict[str, Alias] = frozendict()


def config_path(environ: Mapping[str, str] = os.environ) -> Path:
    """Return $FREEPILOT_CONFIG, else freepilot/config.toml in the XDG config dir."""
    if explicit := environ.get("FREEPILOT_CONFIG"):
        return Path(explicit)
    base = environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "freepilot" / "config.toml"


def load_config(path: Path) -> Config:
    """Read and check a config file. A missing file is an empty config."""
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        message = f"{path}: {error}"
        raise ConfigError(message) from None
    return parse_config(data, path)


def parse_config(data: Mapping[str, object], source: Path) -> Config:
    """Check config data. Errors name the file, table, and key."""
    monitors = data.get("monitors", {})
    if not isinstance(monitors, dict):
        message = f"{source}: [monitors] must be a table"
        raise ConfigError(message)
    return Config(
        monitors=frozendict(
            {
                name: parse_alias(table, f"{source}: [monitors.{name}]")
                for name, table in monitors.items()
            }
        )
    )


def parse_alias(table: object, where: str) -> Alias:
    """Check one [monitors.NAME] table."""
    if not isinstance(table, dict):
        message = f"{where} must be a table"
        raise ConfigError(message)
    if unknown := table.keys() - ALIAS_KEYS:
        message = f"{where} has unknown keys: {', '.join(sorted(unknown))}"
        raise ConfigError(message)
    if not table:
        message = f"{where} needs serial or connector"
        raise ConfigError(message)
    for key, value in table.items():
        if not isinstance(value, str):
            message = f"{where} {key} must be a string"
            raise ConfigError(message)
    return Alias(**table)
