"""Read freepilot's config.toml."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Mapping

from freepilot.errors import FreepilotError
from freepilot.features import BENQ_RD_FEATURES, FEATURE_SETS, MAX_LEVEL

ALIAS_KEYS = frozenset({"serial", "connector", "model"})
PROFILE_LEVELS = frozenset({"brightness", "contrast", "sharpness", "volume"})
PROFILE_CHOICES = frozenset({"picture-mode", "input", "mute"})
MAX_CODE, MAX_VALUE = 0xFF, 0xFFFF
# Raw codes a profile may not set. They switch the monitor away from this
# machine, cut its power, reset it, or have a named key that is applied in
# the right order.
DISRUPTIVE_CODES: frozendict[int, str] = frozendict(
    {
        0x04: "factory reset",
        0x08: "colour reset",
        0x60: "input; use the input key",
        0xD6: "power mode",
        0xDC: "picture mode; use the picture-mode key",
        0xE4: "KVM switch",
    }
)


class ConfigError(FreepilotError):
    """config.toml is not valid TOML or has a value freepilot can't use."""


@dataclass(frozen=True, slots=True)
class Alias:
    """A name for one monitor. A monitor matches when serial and connector do.

    model forces a feature set, such as benq-rd, when the EDID is missing or
    doesn't identify the monitor.
    """

    serial: str | None = None
    connector: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class Profile:
    """Named settings to apply together.

    settings holds named keys: levels as integers, choices as names. vcp holds
    raw codes. monitor is a --monitor selector used when the command line
    names no monitor.
    """

    settings: frozendict[str, int | str] = frozendict()
    vcp: frozendict[int, int] = frozendict()
    monitor: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    """Everything freepilot reads from config.toml."""

    monitors: frozendict[str, Alias] = frozendict()
    profiles: frozendict[str, Profile] = frozendict()


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
    return Config(
        monitors=frozendict(
            {
                name: parse_alias(table, f"{source}: [monitors.{name}]")
                for name, table in tables(data, "monitors", source).items()
            }
        ),
        profiles=frozendict(
            {
                name: parse_profile(table, f"{source}: [profiles.{name}]")
                for name, table in tables(data, "profiles", source).items()
            }
        ),
    )


def tables(data: Mapping[str, object], key: str, source: Path) -> dict[str, object]:
    """Return a top-level table, or an empty one when it is missing."""
    found = data.get(key, {})
    if not isinstance(found, dict):
        message = f"{source}: [{key}] must be a table"
        raise ConfigError(message)
    return found


def parse_alias(table: object, where: str) -> Alias:
    """Check one [monitors.NAME] table."""
    if not isinstance(table, dict):
        message = f"{where} must be a table"
        raise ConfigError(message)
    if unknown := table.keys() - ALIAS_KEYS:
        message = f"{where} has unknown keys: {', '.join(sorted(unknown))}"
        raise ConfigError(message)
    if not table.keys() & {"serial", "connector"}:
        message = f"{where} needs serial or connector"
        raise ConfigError(message)
    for key, value in table.items():
        if not isinstance(value, str):
            message = f"{where} {key} must be a string"
            raise ConfigError(message)
    if (model := table.get("model")) is not None and model not in FEATURE_SETS:
        message = f"{where} model must be one of {', '.join(FEATURE_SETS)}"
        raise ConfigError(message)
    return Alias(**table)


def parse_profile(table: object, where: str) -> Profile:
    """Check one [profiles.NAME] table, before anything is written.

    Whether a choice name fits the monitor is checked when the profile is
    applied, once freepilot knows which monitor it is.
    """
    if not isinstance(table, dict):
        message = f"{where} must be a table"
        raise ConfigError(message)
    settings: dict[str, int | str] = {}
    vcp: dict[int, int] = {}
    monitor = None
    for key, value in table.items():
        match key:
            case "monitor":
                monitor = require_string(value, f"{where} monitor")
            case "vcp":
                vcp = parse_vcp_table(value, f"{where} vcp")
            case _ if key in PROFILE_LEVELS:
                settings[key] = require_int(value, f"{where} {key}", MAX_LEVEL)
            case _ if key in PROFILE_CHOICES:
                settings[key] = require_string(value, f"{where} {key}")
            case _:
                message = f"{where} has an unknown key: {key}"
                raise ConfigError(message)
    named_codes = {BENQ_RD_FEATURES[name].code for name in settings}
    if duplicates := vcp.keys() & named_codes:
        message = f"{where} sets VCP 0x{min(duplicates):02x} both by name and in vcp"
        raise ConfigError(message)
    if not settings and not vcp:
        message = f"{where} sets nothing"
        raise ConfigError(message)
    return Profile(frozendict(settings), frozendict(vcp), monitor)


def parse_vcp_table(table: object, where: str) -> dict[int, int]:
    """Check a vcp table: hex or decimal string keys, integer values."""
    if not isinstance(table, dict):
        message = f"{where} must be a table"
        raise ConfigError(message)
    vcp = {}
    for key, value in table.items():
        try:
            code = int(key, 0)
        except ValueError:
            message = f'{where} key {key!r} is not a number such as "0xd1"'
            raise ConfigError(message) from None
        if not 0 <= code <= MAX_CODE:
            message = f"{where} code {key} is outside 0-0xff"
            raise ConfigError(message)
        if reason := DISRUPTIVE_CODES.get(code):
            message = f"{where} can't set 0x{code:02x} ({reason})"
            raise ConfigError(message)
        vcp[code] = require_int(value, f"{where} {key}", MAX_VALUE)
    return vcp


def require_string(value: object, where: str) -> str:
    """Return a string value, or raise naming the key."""
    if not isinstance(value, str):
        message = f"{where} must be a string"
        raise ConfigError(message)
    return value


def require_int(value: object, where: str, maximum: int) -> int:
    """Return an integer from 0 to maximum. TOML booleans don't count."""
    if isinstance(value, bool) or not isinstance(value, int):
        message = f"{where} must be an integer"
        raise ConfigError(message)
    if not 0 <= value <= maximum:
        message = f"{where} is outside 0-{maximum}"
        raise ConfigError(message)
    return value
