"""Control BenQ RD series monitors over DDC/CI through ddcutil."""

import argparse

from freelink.ddcutil import Ddcutil, DdcutilError, Reading
from freelink.features import (
    FEATURES,
    INPUT_SOURCES,
    MAX_LEVEL,
    PICTURE_MODES,
    feature_name,
)
from freelink.monitor import Monitor


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
        message = f"unknown feature {text!r}; run 'freelink codes' for names"
        raise argparse.ArgumentTypeError(message) from None


def format_reading(reading: Reading | None) -> str:
    """Show continuous values as current/max and the rest in hex."""
    if reading is None or reading.value is None:
        return "unreadable"
    if reading.maximum is not None:
        return f"{reading.value}/{reading.maximum}"
    return f"0x{reading.value:02x}"


def show_status(monitor: Monitor) -> None:
    """Print the common settings."""
    status = monitor.status()
    rows = {
        "picture-mode": status.picture_mode or "unreadable",
        "input": status.input_source or "unreadable",
        "brightness": format_reading(status.brightness),
        "contrast": format_reading(status.contrast),
        "volume": format_reading(status.volume),
        "mute": {True: "on", False: "off", None: "unreadable"}[status.muted],
    }
    for name, shown in rows.items():
        print(f"{name:<14} {shown}")


def show_readings(monitor: Monitor, codes: list[int]) -> None:
    """Print each requested feature in the order given."""
    readings = monitor.read(*codes)
    for code in codes:
        label = feature_name(code) or f"0x{code:02x}"
        print(f"{label:<24} {format_reading(readings.get(code))}")


def list_codes() -> None:
    """Print every VCP code freelink knows about."""
    for name, feature in sorted(FEATURES.items(), key=lambda item: item[1].code):
        marker = "" if feature.values_confirmed else "  (values unconfirmed)"
        print(f"0x{feature.code:02x}  {name:<24} {feature.description}{marker}")


def build_parser() -> argparse.ArgumentParser:
    """Define the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--display", help="ddcutil display number")
    target.add_argument("--bus", help="I2C bus number, as in /dev/i2c-N")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="Show picture mode, input, and levels")
    commands.add_parser("codes", help="List known VCP codes")

    mode = commands.add_parser("mode", help="Set the picture mode")
    mode.add_argument("name", choices=PICTURE_MODES)

    source = commands.add_parser("input", help="Switch the input source")
    source.add_argument("name", choices=INPUT_SOURCES)

    for name in ("brightness", "contrast", "volume"):
        level = commands.add_parser(name, help=f"Set {name}, 0-100")
        level.add_argument("value", type=percent, metavar="0-100")

    mute = commands.add_parser("mute", help="Mute or unmute the speakers")
    mute.add_argument("state", choices=("on", "off"))

    get = commands.add_parser(
        "get",
        help="Read features by name or by decimal or 0x VCP code; see 'codes'",
    )
    get.add_argument("features", nargs="+", type=resolve_code)

    set_ = commands.add_parser(
        "set", help="Write a decimal or 0x value to a feature named or numbered"
    )
    set_.add_argument("feature", type=resolve_code)
    set_.add_argument("value", type=parse_int)
    return parser


def run(monitor: Monitor, arguments: argparse.Namespace) -> None:
    """Carry out one monitor command."""
    match arguments.command:
        case "status":
            show_status(monitor)
        case "mode":
            monitor.set_picture_mode(arguments.name)
        case "input":
            monitor.set_input(arguments.name)
        case "brightness" | "contrast" | "volume":
            monitor.set_level(arguments.command, arguments.value)
        case "mute":
            monitor.set_muted(muted=arguments.state == "on")
        case "get":
            show_readings(monitor, arguments.features)
        case "set":
            monitor.write(arguments.feature, arguments.value)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one command."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "codes":
        list_codes()
        return

    if arguments.display:
        transport = Ddcutil(("--display", arguments.display))
    elif arguments.bus:
        transport = Ddcutil(("--bus", arguments.bus))
    else:
        transport = Ddcutil()

    try:
        run(Monitor(transport), arguments)
    except DdcutilError as error:
        parser.exit(1, f"freelink: {error}\n")


if __name__ == "__main__":
    main()
