"""Control monitors over DDC/CI, with BenQ RD series extras."""

import argparse
import json
from typing import NoReturn

from freepilot.errors import FreepilotError
from freepilot.features import (
    BENQ_INPUTS,
    BENQ_RD_FEATURES,
    FEATURE_SETS,
    MAX_LEVEL,
    MCCS_INPUTS,
    MUTE_STATES,
    PICTURE_MODES,
)
from freepilot.render import (
    Output,
    capabilities_output,
    codes_output,
    displays_output,
    readings_output,
    status_output,
)

# Only monitor commands need a transport, so --help skips loading them.
lazy from freepilot import displays, targets
lazy from freepilot.capabilities import (
    Capabilities,
    CapabilityError,
    parse_capabilities,
    write_problem,
)
lazy from freepilot.config import Config, config_path, load_config
lazy from freepilot.features import FeatureSet
lazy from freepilot.monitor import Monitor, WriteCheck
lazy from freepilot.vcp import Transport

# Names every feature set uses for the same codes, so parsing needs no monitor.
INPUT_NAMES = tuple(dict.fromkeys([*BENQ_INPUTS, *MCCS_INPUTS]))


def parse_int(text: str) -> int:
    """Accept decimal or 0x-prefixed hex."""
    return int(text, 0)


def percent(text: str) -> int:
    """Accept an integer from 0 to 100."""
    value = int(text)
    if not 0 <= value <= MAX_LEVEL:
        message = f"expected 0-{MAX_LEVEL}"
        raise argparse.ArgumentTypeError(message)
    return value


def resolve_code(text: str) -> int:
    """Accept a feature name or a numeric VCP code."""
    if text in BENQ_RD_FEATURES:
        return BENQ_RD_FEATURES[text].code
    try:
        return parse_int(text)
    except ValueError:
        message = f"unknown feature {text!r}; run 'freepilot codes' for names"
        raise argparse.ArgumentTypeError(message) from None


def build_parser() -> argparse.ArgumentParser:
    """Define the command line."""
    # --json works before or after the command. Subcommands default it to
    # SUPPRESS so they don't reset a --json given before the command.
    json_help = "Print JSON for read commands, and errors as JSON on stderr"
    output = argparse.ArgumentParser(add_help=False)
    output.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help=json_help
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help=json_help)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--display", help="ddcutil display number")
    target.add_argument("--bus", type=int, help="I2C bus number, as in /dev/i2c-N")
    target.add_argument(
        "--monitor",
        help="Config alias, serial, connector (DP-1), or part of the model name",
    )
    parser.add_argument(
        "--transport",
        choices=("ddcutil", "i2c"),
        default="ddcutil",
        help="Run ddcutil (default), or talk to /dev/i2c-N directly (untested)",
    )
    parser.add_argument(
        "--model",
        choices=FEATURE_SETS,
        help="Feature set to use instead of identifying the monitor by its EDID",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Refuse writes the monitor's capability string doesn't list",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "capabilities",
        parents=[output],
        help="Show the monitor's capability string, with freepilot's names",
    )

    commands.add_parser("list", parents=[output], help="List connected monitors")

    commands.add_parser(
        "status", parents=[output], help="Show picture mode, input, and levels"
    )
    commands.add_parser("codes", parents=[output], help="List known VCP codes")

    mode = commands.add_parser("mode", help="Set the picture mode")
    mode.add_argument("name", choices=PICTURE_MODES)

    source = commands.add_parser("input", help="Switch the input source")
    source.add_argument("name", choices=INPUT_NAMES)

    for name in ("brightness", "contrast", "volume"):
        level = commands.add_parser(name, help=f"Set {name}, 0-100")
        level.add_argument("value", type=percent, metavar="0-100")

    mute = commands.add_parser("mute", help="Mute or unmute the speakers")
    mute.add_argument("state", choices=MUTE_STATES)

    get = commands.add_parser(
        "get",
        parents=[output],
        help="Read features by name or by decimal or 0x VCP code; see 'codes'",
    )
    get.add_argument("features", nargs="+", type=resolve_code)

    set_ = commands.add_parser(
        "set", help="Write a decimal or 0x value to a feature named or numbered"
    )
    set_.add_argument("feature", type=resolve_code)
    set_.add_argument("value", type=parse_int)
    return parser


def run(monitor: Monitor, arguments: argparse.Namespace) -> Output | None:
    """Carry out one monitor command. Read commands return what to show."""
    features = monitor.features
    match arguments.command:
        case "status":
            return status_output(monitor.status(), features)
        case "capabilities":
            return capabilities_output(monitor.capabilities(), features)
        case "get":
            readings = monitor.read(*arguments.features)
            return readings_output(arguments.features, readings, features)
        case "mode":
            monitor.set_picture_mode(arguments.name)
        case "input":
            monitor.set_input(arguments.name)
        case "brightness" | "contrast" | "volume":
            monitor.set_level(arguments.command, arguments.value)
        case "mute":
            monitor.set_muted(muted=arguments.state == "on")
        case "set":
            monitor.write(arguments.feature, arguments.value)
    return None


def show(output: Output, *, as_json: bool) -> None:
    """Print a read command's result as text lines or one line of JSON."""
    if as_json:
        print(json.dumps(output.data))
    else:
        print("\n".join(output.lines))


def fail(parser: argparse.ArgumentParser, message: str, *, as_json: bool) -> NoReturn:
    """Exit 1 with an error on stderr, as JSON when --json was given."""
    if as_json:
        parser.exit(1, json.dumps({"level": "error", "message": message}) + "\n")
    parser.exit(1, f"freepilot: {message}\n")


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one command."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.transport == "i2c" and arguments.display:
        parser.error("--display is ddcutil's numbering; use --bus or --monitor")
    try:
        output = dispatch(arguments)
    except FreepilotError as error:
        fail(parser, str(error), as_json=arguments.json)
    if output is not None:
        show(output, as_json=arguments.json)


def dispatch(arguments: argparse.Namespace) -> Output | None:
    """Resolve the monitor a command means, then run the command on it."""
    connected = displays.find_displays()
    if arguments.command == "list":
        return displays_output(connected)
    selection = targets.Selection(
        display_number=arguments.display,
        bus=arguments.bus,
        monitor=arguments.monitor,
        transport=arguments.transport,
        model=arguments.model,
    )
    # Only --monitor needs the config, so a broken config can't stop the rest.
    config = load_config(config_path()) if selection.monitor else Config()
    target = targets.resolve(selection, connected, config.monitors)
    if arguments.command == "codes":
        return codes_output(target.features)
    transport = targets.connect(selection, target)
    check = strict_check(transport, target.features) if arguments.strict else None
    return run(Monitor(transport, target.features, check), arguments)


def strict_check(transport: Transport, features: FeatureSet) -> WriteCheck:
    """Refuse writes the capability string doesn't list. Fetches it once."""
    fetched: list[Capabilities] = []

    def check(code: int, value: int) -> None:
        if not fetched:
            fetched.append(parse_capabilities(transport.capabilities()))
        feature = features.feature_for(code)
        is_choice = feature is not None and feature.kind == "choice"
        if problem := write_problem(fetched[0], code, value, check_value=is_choice):
            message = f"{problem}; drop --strict to send it anyway"
            raise CapabilityError(message)

    return check


if __name__ == "__main__":
    main()
