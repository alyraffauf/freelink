"""Control BenQ RD series monitors over DDC/CI through ddcutil."""

import argparse
import subprocess
import time
from dataclasses import dataclass

# Picture modes write (SHCode << 8) | Code to VCP 0xDC. Every RD model uses
# SHCode 0, so the value is the mode code.
PICTURE_MODES = {
    "coding-light": 0x31,
    "coding-dark": 0x30,
    "coding-paper": 0x3A,
    "m-book": 0x0F,
    "cinema": 0x32,
    "game": 0x28,
    "epaper": 0x1F,
    "srgb": 0x0A,
    "user": 0x12,
    "hdr": 0x23,
}

INPUT_SOURCES = {
    "d-sub": 0x01,
    "dvi": 0x03,
    "displayport": 0x0F,
    "mini-displayport": 0x10,
    "hdmi": 0x11,
    "hdmi1": 0x11,
    "hdmi2": 0x12,
    "usb-c": 0x13,
    "usb-c2": 0x14,
    "thunderbolt": 0x15,
    "hdmi3": 0x16,
}


@dataclass(frozen=True)
class Feature:
    """A named VCP code and whether Display Pilot 2's use of it is understood."""

    code: int
    description: str
    known: bool = True


# Codes Display Pilot 2 reads or writes on RD models. Unknown features have
# a confirmed code but unconfirmed values.
FEATURES = {
    "brightness": Feature(0x10, "Brightness, 0-100"),
    "contrast": Feature(0x12, "Contrast, 0-100"),
    "color-temperature": Feature(0x14, "Colour temperature preset", known=False),
    "red-gain": Feature(0x16, "Red gain", known=False),
    "green-gain": Feature(0x18, "Green gain", known=False),
    "blue-gain": Feature(0x1A, "Blue gain", known=False),
    "low-blue-light": Feature(0x19, "Low blue light level", known=False),
    "gamut": Feature(0x5F, "Colour gamut", known=False),
    "input": Feature(0x60, "Input source"),
    "volume": Feature(0x62, "Speaker volume, 0-100"),
    "gamma": Feature(0x72, "Gamma preset", known=False),
    "pip-pbp": Feature(0x7D, "PIP/PBP mode", known=False),
    "bright-intelligence": Feature(0x81, "Bright Intelligence Plus", known=False),
    "sharpness": Feature(0x87, "Sharpness"),
    "mute": Feature(0x8D, "Audio mute, 1 muted, 2 unmuted"),
    "audio-mode": Feature(0x94, "Audio mode", known=False),
    "auto-pivot": Feature(0xAA, "Auto pivot status", known=False),
    "night-protection-level": Feature(0xD0, "Night protection level", known=False),
    "night-protection": Feature(0xD1, "Night hours protection", known=False),
    "power-mode": Feature(0xD6, "Power mode"),
    "backlight": Feature(0xD7, "Backlight switch", known=False),
    "backlight-level": Feature(0xD9, "Backlight level", known=False),
    "picture-mode": Feature(0xDC, "Picture mode"),
    "bi-sensor": Feature(0xE2, "Bright Intelligence sensor", known=False),
    "light-meter": Feature(0xE3, "Light meter", known=False),
    "kvm": Feature(0xE4, "KVM switch", known=False),
    "bi-sensitivity": Feature(0xE5, "Bright Intelligence sensitivity", known=False),
    "daisy-chain": Feature(0xE6, "DisplayPort daisy chain", known=False),
    "eco-privacy": Feature(0xE7, "Eco privacy (MoonHalo) timer", known=False),
    "eco-privacy-mode": Feature(0xE8, "Eco privacy mode", known=False),
    "eco-privacy-sensitivity": Feature(0xE9, "Eco privacy sensor", known=False),
    "ai-contrast": Feature(0xF3, "AI contrast", known=False),
    "dual-view": Feature(0xF4, "Dual view", known=False),
    "uniformity": Feature(0xFA, "Uniformity", known=False),
    "color-weakness": Feature(0xFD, "Colour weakness filter", known=False),
}

STATUS = ("picture-mode", "input", "brightness", "contrast", "volume", "mute")

MAX_LEVEL = 100
MUTED, UNMUTED = 1, 2

# Display Pilot 2 waits this long, in milliseconds, after writing these codes.
WRITE_DELAYS = {0xDC: 500, 0x08: 5000, 0x04: 2000, 0x94: 700, 0xE4: 1000, 0x13: 500}


@dataclass(frozen=True)
class Reading:
    """One parsed ddcutil reading."""

    code: int
    value: int | None
    maximum: int | None = None


def parse_terse(output: str) -> dict[int, Reading]:
    """Parse ddcutil --terse getvcp lines into readings keyed by VCP code."""
    readings = {}
    for line in output.splitlines():
        match line.split():
            case ["VCP", code, "C", current, maximum]:
                reading = Reading(int(code, 16), int(current), int(maximum))
            case ["VCP", code, "SNC", value]:
                reading = Reading(int(code, 16), hex_byte(value))
            case ["VCP", code, "CNC", _, _, high, low]:
                # mh ml sh sl; the current value is the low word.
                reading = Reading(int(code, 16), hex_byte(high) << 8 | hex_byte(low))
            case ["VCP", code, *_]:
                reading = Reading(int(code, 16), None)
            case _:
                continue
        readings[reading.code] = reading
    return readings


def hex_byte(text: str) -> int:
    """Parse a ddcutil hex byte such as x1f."""
    return int(text.removeprefix("x"), 16)


@dataclass(frozen=True)
class Monitor:
    """Run ddcutil against one display."""

    selector: tuple[str, ...] = ()

    def ddcutil(self, *arguments: str) -> str:
        """Run ddcutil and return stdout, raising on failure."""
        result = subprocess.run(
            ["ddcutil", *self.selector, *arguments],
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(message or f"ddcutil exited with {result.returncode}")
        return result.stdout

    def get(self, *codes: int) -> dict[int, Reading]:
        """Read one or more VCP codes."""
        return parse_terse(
            self.ddcutil("getvcp", "--terse", *(f"0x{code:02x}" for code in codes))
        )

    def set(self, code: int, value: int) -> None:
        """Write a VCP code, then wait as long as Display Pilot 2 does."""
        self.ddcutil("setvcp", f"0x{code:02x}", str(value))
        time.sleep(WRITE_DELAYS.get(code, 0) / 1000)


def name_for(table: dict[str, int], value: int | None) -> str:
    """Return the first name for a value, or its hex form."""
    if value is None:
        return "unreadable"
    names = [name for name, candidate in table.items() if candidate == value]
    return names[0] if names else f"0x{value:02x}"


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


def format_reading(reading: Reading) -> str:
    """Show continuous values as current/max and the rest in hex."""
    if reading.value is None:
        return "unreadable"
    if reading.maximum is not None:
        return f"{reading.value}/{reading.maximum}"
    return f"0x{reading.value:02x}"


def resolve_code(text: str) -> int:
    """Accept a feature name or a numeric VCP code."""
    if text in FEATURES:
        return FEATURES[text].code
    try:
        return parse_int(text)
    except ValueError:
        message = f"unknown feature {text!r}"
        raise argparse.ArgumentTypeError(message) from None


def show_status(monitor: Monitor) -> None:
    """Print the common settings."""
    readings = monitor.get(*(FEATURES[name].code for name in STATUS))
    for name in STATUS:
        reading = readings.get(FEATURES[name].code)
        value = reading.value if reading else None
        if name == "picture-mode":
            shown = name_for(PICTURE_MODES, value)
        elif name == "input":
            shown = name_for(INPUT_SOURCES, value)
        elif name == "mute":
            shown = {MUTED: "on", UNMUTED: "off"}.get(value or 0, "unreadable")
        else:
            shown = format_reading(reading or Reading(0, None))
        print(f"{name:<14} {shown}")


def show_readings(monitor: Monitor, codes: list[int]) -> None:
    """Print each requested feature in the order given."""
    readings = monitor.get(*codes)
    for code in codes:
        names = [name for name, feature in FEATURES.items() if feature.code == code]
        label = names[0] if names else f"0x{code:02x}"
        print(f"{label:<24} {format_reading(readings.get(code, Reading(code, None)))}")


def list_codes() -> None:
    """Print every VCP code this script knows about."""
    for name, feature in sorted(FEATURES.items(), key=lambda item: item[1].code):
        marker = "" if feature.known else "  (values unconfirmed)"
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

    get = commands.add_parser("get", help="Read features by name or VCP code")
    get.add_argument("features", nargs="+", type=resolve_code)

    set_ = commands.add_parser("set", help="Write a raw value to a feature")
    set_.add_argument("feature", type=resolve_code)
    set_.add_argument("value", type=parse_int)
    return parser


def run(monitor: Monitor, arguments: argparse.Namespace) -> None:
    """Carry out one monitor command."""
    match arguments.command:
        case "status":
            show_status(monitor)
        case "mode":
            monitor.set(FEATURES["picture-mode"].code, PICTURE_MODES[arguments.name])
        case "input":
            monitor.set(FEATURES["input"].code, INPUT_SOURCES[arguments.name])
        case "brightness" | "contrast" | "volume":
            monitor.set(FEATURES[arguments.command].code, arguments.value)
        case "mute":
            state = MUTED if arguments.state == "on" else UNMUTED
            monitor.set(FEATURES["mute"].code, state)
        case "get":
            show_readings(monitor, arguments.features)
        case "set":
            monitor.set(arguments.feature, arguments.value)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one command."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "codes":
        list_codes()
        return

    if arguments.display:
        monitor = Monitor(("--display", arguments.display))
    elif arguments.bus:
        monitor = Monitor(("--bus", arguments.bus))
    else:
        monitor = Monitor()

    try:
        run(monitor, arguments)
    except FileNotFoundError:
        parser.exit(1, "freelink: ddcutil is not installed\n")
    except RuntimeError as error:
        parser.exit(1, f"freelink: {error}\n")


if __name__ == "__main__":
    main()
