"""Read and write VCP codes by running ddcutil."""

import subprocess
from contextlib import nullcontext
from dataclasses import dataclass

from freepilot.vcp import Reading, TransportError


class DdcutilError(TransportError):
    """ddcutil is missing, failed, or printed output that does not parse."""


def parse_terse(output: str) -> dict[int, Reading]:
    """Parse ddcutil --terse getvcp output into readings keyed by VCP code."""
    readings = {}
    for line in output.splitlines():
        try:
            reading = parse_terse_line(line)
        except ValueError as error:
            message = f"unexpected ddcutil output: {line!r}"
            raise DdcutilError(message) from error
        if reading is not None:
            readings[reading.code] = reading
    return readings


def parse_terse_line(line: str) -> Reading | None:
    """Parse one --terse line, or return None for lines that are not readings."""
    match line.split():
        case ["VCP", code, "C", current, maximum]:
            return Reading(int(code, 16), int(current), int(maximum))
        case ["VCP", code, "SNC", value]:
            return Reading(int(code, 16), hex_byte(value))
        case ["VCP", code, "CNC", _, _, high, low]:
            # The four bytes are maximum high, maximum low, current high, and
            # current low. Keep the current value.
            return Reading(int(code, 16), hex_byte(high) << 8 | hex_byte(low))
        case ["VCP", code, *_]:
            return Reading(int(code, 16), None)
        case _:
            return None


def hex_byte(text: str) -> int:
    """Parse a ddcutil hex byte such as x1f."""
    return int(text.removeprefix("x"), 16)


@dataclass(frozen=True, slots=True)
class Ddcutil:
    """Run ddcutil against one display.

    selector holds ddcutil's display options, such as ("--bus", "7"). Empty
    means ddcutil's default display.
    """

    selector: tuple[str, ...] = ()

    def session(self) -> nullcontext[None]:
        """Do nothing: ddcutil locks the bus itself on every call.

        Holding a lock here would make freepilot's own ddcutil calls wait on it.
        """
        return nullcontext()

    def run(self, *arguments: str) -> str:
        """Run ddcutil and return its stdout."""
        try:
            result = subprocess.run(
                ["ddcutil", *self.selector, *arguments],
                check=False,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError:
            message = "ddcutil is not installed"
            raise DdcutilError(message) from None
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise DdcutilError(message or f"ddcutil exited with {result.returncode}")
        return result.stdout

    def get(self, *codes: int) -> dict[int, Reading]:
        """Read one or more VCP codes."""
        return parse_terse(
            self.run("getvcp", "--terse", *(f"0x{code:02x}" for code in codes))
        )

    def set(self, code: int, value: int) -> None:
        """Write one VCP code."""
        self.run("setvcp", f"0x{code:02x}", str(value))

    def capabilities(self) -> str:
        """Fetch the raw capability string."""
        return parse_capabilities_output(self.run("capabilities", "--terse"))


def parse_capabilities_output(output: str) -> str:
    """Take the string from ddcutil's 'Unparsed capabilities string: ...' line."""
    for line in output.splitlines():
        _, found, rest = line.partition("capabilities string:")
        if found:
            return rest.strip()
    message = f"no capability string in ddcutil output: {output.strip()!r}"
    raise DdcutilError(message)
