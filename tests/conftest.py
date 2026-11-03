"""Shared fixtures: a fake ddcutil and no write delays."""

import subprocess
lazy from pathlib import Path

import pytest

from freepilot import ddcutil, monitor

TERSE = """\
VCP dc SNC x31
VCP 60 SNC x13
VCP 10 C 42 100
VCP 12 C 50 100
VCP 62 C 20 100
VCP 8d SNC x02
VCP e4 ERR
"""


class FakeRun:
    """Stand in for subprocess.run: record calls, answer getvcp from output."""

    def __init__(self, output: str = TERSE, returncode: int = 0) -> None:
        """Store the reply every call returns."""
        self.output = output
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(
        self, command: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        """Record the command and return the canned reply."""
        self.calls.append(command)
        stdout = self.output if "getvcp" in command else ""
        stderr = "" if self.returncode == 0 else "Display not found"
        return subprocess.CompletedProcess(command, self.returncode, stdout, stderr)


@pytest.fixture(autouse=True)
def no_write_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the post-write sleeps in every test."""
    monkeypatch.setattr(monitor.time, "sleep", lambda _: None)


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> FakeRun:
    """Replace subprocess.run for the ddcutil transport."""
    fake = FakeRun()
    monkeypatch.setattr(ddcutil.subprocess, "run", fake)
    return fake


def make_edid(
    manufacturer: bytes = b"\x09\xd1",
    product: int = 0x8034,
    serial_number: int = 0,
    texts: dict[int, bytes] | None = None,
) -> bytes:
    """Build a valid 128-byte EDID base block.

    manufacturer is the raw big-endian bytes 8-9 (09 d1 is BNQ). texts maps a
    display descriptor tag to its text, already padded or not.
    """
    block = bytearray(128)
    block[:8] = bytes.fromhex("00ffffffffffff00")
    block[8:10] = manufacturer
    block[10:12] = product.to_bytes(2, "little")
    block[12:16] = serial_number.to_bytes(4, "little")
    # Slot 0 holds a detailed timing (non-zero pixel clock), like real EDIDs.
    block[54:56] = (14850).to_bytes(2, "little")
    for slot, (tag, text) in enumerate((texts or {}).items(), start=1):
        if len(text) > 13:
            message = f"descriptor text is {len(text)} bytes, the limit is 13"
            raise ValueError(message)
        offset = 54 + 18 * slot
        block[offset + 3] = tag
        block[offset + 5 : offset + 5 + len(text)] = text
    block[127] = -sum(block[:127]) % 256
    return bytes(block)


def make_connector(  # noqa: PLR0913 - one keyword per sysfs file
    root: Path,
    name: str,
    *,
    status: str = "connected",
    edid: bytes = b"",
    ddc_bus: int | None = None,
    child_buses: tuple[int, ...] = (),
) -> Path:
    """Create a fake /sys/class/drm connector directory under root."""
    connector = root / name
    connector.mkdir(parents=True)
    (connector / "status").write_text(f"{status}\n")
    (connector / "edid").write_bytes(edid)
    if ddc_bus is not None:
        target = root / "devices" / f"i2c-{ddc_bus}"
        target.mkdir(parents=True, exist_ok=True)
        (connector / "ddc").symlink_to(target)
    for bus in child_buses:
        (connector / f"i2c-{bus}").mkdir()
    return connector
