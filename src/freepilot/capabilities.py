"""Parse the capability string a monitor reports over DDC/CI.

Monitors get this string wrong in many ways, so the parser is lenient. It
keeps what it can read and marks what it can't, and never refuses a whole
string. Monitors also leave out codes they support, so capabilities are
advisory: freepilot only refuses an unlisted write under --strict.
"""

import re
import string
from dataclasses import dataclass, field

from freepilot.errors import FreepilotError

GROUP_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
HEX = frozenset(string.hexdigits)


class CapabilityError(FreepilotError):
    """--strict refused a write the monitor does not list."""


@dataclass(frozen=True, slots=True)
class VcpEntry:
    """One code from the vcp group.

    values is None when the monitor gave no list. malformed means it gave a
    list freepilot couldn't read, such as nested groups.
    """

    values: tuple[int, ...] | None = None
    malformed: bool = False


@dataclass(frozen=True, slots=True)
class Capabilities:
    """The parts of a capability string freepilot uses. raw keeps the rest."""

    raw: str
    model: str | None = None
    display_type: str | None = None
    mccs_version: str | None = None
    commands: tuple[int, ...] = ()
    vcp: frozendict[int, VcpEntry] = field(default_factory=frozendict)
    other: frozendict[str, str] = field(default_factory=frozendict)


def parse_capabilities(raw: str) -> Capabilities:
    """Parse a capability string such as (prot(monitor)vcp(10 12 60(0F 11)))."""
    groups = split_groups(raw)
    known = {"model", "type", "mccs_ver", "cmds", "vcp"}
    return Capabilities(
        raw=raw,
        model=groups.get("model"),
        display_type=groups.get("type"),
        mccs_version=groups.get("mccs_ver"),
        commands=hex_pairs(groups.get("cmds", "")) or (),
        vcp=frozendict(parse_vcp(groups.get("vcp", ""))),
        other=frozendict({k: v for k, v in groups.items() if k not in known}),
    )


def split_groups(text: str) -> dict[str, str]:
    """Find name(...) groups, ignoring outer parentheses and stray text.

    A repeated group, as some monitors send for vcp, is joined with a space.
    An unclosed group runs to the end of the text.
    """
    groups: dict[str, str] = {}
    position = 0
    while match := GROUP_NAME.search(text, position):
        content, position = balanced(text, match.end())
        name = match[1].lower()
        groups[name] = f"{groups[name]} {content}" if name in groups else content
    return {name: content.strip() for name, content in groups.items()}


def balanced(text: str, start: int) -> tuple[str, int]:
    """Return the text up to the parenthesis that closes one opened before start."""
    depth = 1
    for index in range(start, len(text)):
        match text[index]:
            case "(":
                depth += 1
            case ")":
                depth -= 1
                if depth == 0:
                    return text[start:index], index + 1
    return text[start:], len(text)


def parse_vcp(text: str) -> dict[int, VcpEntry]:
    """Parse vcp group content: hex codes, each optionally followed by (values).

    Codes may be packed without spaces, as in 0203(10 00)04.
    """
    entries: dict[int, VcpEntry] = {}
    position = 0
    while position < len(text):
        pair = text[position : position + 2]
        if len(pair) < 2 or not HEX.issuperset(pair):  # noqa: PLR2004 - a hex byte
            position += 1
            continue
        code = int(pair, 16)
        position += 2
        while position < len(text) and text[position].isspace():
            position += 1
        if text.startswith("(", position):
            content, position = balanced(text, position + 1)
            values = hex_pairs(content)
            entries[code] = VcpEntry(values, malformed=values is None)
        else:
            entries.setdefault(code, VcpEntry())
    return entries


def hex_pairs(text: str) -> tuple[int, ...] | None:
    """Read hex bytes, spaced or packed. None if the text isn't whole bytes."""
    digits = "".join(text.split())
    if len(digits) % 2 or not HEX.issuperset(digits):
        return None
    return tuple(int(digits[i : i + 2], 16) for i in range(0, len(digits), 2))


def write_problem(
    capabilities: Capabilities, code: int, value: int, *, check_value: bool
) -> str | None:
    """Say why a write isn't listed in the capabilities, or return None.

    Only check values for choice features: lists on continuous features
    aren't ranges, and an unreadable list proves nothing.
    """
    entry = capabilities.vcp.get(code)
    if entry is None:
        return f"the monitor does not list VCP 0x{code:02x}"
    listed = entry.values
    if check_value and listed is not None and value not in listed:
        return f"the monitor does not list value 0x{value:02x} for VCP 0x{code:02x}"
    return None
