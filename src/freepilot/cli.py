"""Control BenQ RD series monitors over DDC/CI through ddcutil."""

import argparse
import json
from typing import NoReturn

from freepilot.errors import FreepilotError
from freepilot.features import (
    FEATURES,
    INPUT_SOURCES,
    MAX_LEVEL,
    MUTE_STATES,
    PICTURE_MODES,
)
from freepilot.render import (
    Output,
    codes_output,
    displays_output,
    readings_output,
    status_output,
)

# Only monitor commands need ddcutil, so codes and --help skip loading it.
lazy from freepilot import displays
lazy from freepilot.config import config_path, load_config
lazy from freepilot.ddcutil import Ddcutil
lazy from freepilot.displays import SelectionError, select_display
lazy from freepilot.i2c import I2c
lazy from freepilot.monitor import Monitor
lazy from freepilot.vcp import Transport


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
    if text in FEATURES:
        return FEATURES[text].code
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
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", parents=[output], help="List connected monitors")

    commands.add_parser(
        "status", parents=[output], help="Show picture mode, input, and levels"
    )
    commands.add_parser("codes", parents=[output], help="List known VCP codes")

    mode = commands.add_parser("mode", help="Set the picture mode")
    mode.add_argument("name", choices=PICTURE_MODES)

    source = commands.add_parser("input", help="Switch the input source")
    source.add_argument("name", choices=INPUT_SOURCES)

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
    match arguments.command:
        case "status":
            return status_output(monitor.status())
        case "get":
            return readings_output(
                arguments.features, monitor.read(*arguments.features)
            )
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
    """Run commands that need no monitor directly, the rest through one."""
    match arguments.command:
        case "codes":
            return codes_output()
        case "list":
            return displays_output(displays.find_displays())
        case _:
            return run(Monitor(connect(arguments)), arguments)


def connect(arguments: argparse.Namespace) -> Transport:
    """Build the transport for the monitor the options name.

    freepilot finds the bus itself for --monitor, so both transports pick
    the same monitor. Without a selector, ddcutil uses its default display
    and the i2c transport uses the only connected monitor.
    """
    if arguments.display:
        return Ddcutil(("--display", arguments.display))
    bus = selected_bus(arguments)
    if arguments.transport == "i2c":
        return I2c(default_bus() if bus is None else bus)
    return Ddcutil() if bus is None else Ddcutil(("--bus", str(bus)))


def selected_bus(arguments: argparse.Namespace) -> int | None:
    """Return the bus --bus or --monitor names, or None when neither was given."""
    if arguments.bus is not None:
        return arguments.bus
    if not arguments.monitor:
        return None
    aliases = load_config(config_path()).monitors
    display = select_display(displays.find_displays(), arguments.monitor, aliases)
    if display.bus is None:
        message = f"{display.describe()} has no DDC bus in sysfs; try --bus"
        raise SelectionError(message)
    return display.bus


def default_bus() -> int:
    """Return the bus of the only connected monitor that has one."""
    found = [display for display in displays.find_displays() if display.bus is not None]
    match found:
        case [display] if display.bus is not None:
            return display.bus
        case []:
            message = "no connected monitor has a DDC bus in sysfs; pass --bus"
        case _:
            names = ", ".join(display.describe() for display in found)
            message = (
                f"several monitors are connected ({names}); pick one with --monitor"
            )
    raise SelectionError(message)


if __name__ == "__main__":
    main()
