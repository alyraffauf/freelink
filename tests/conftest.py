"""Shared fixtures: a fake ddcutil and no write delays."""

import subprocess
from contextlib import contextmanager
lazy from collections.abc import Generator
lazy from pathlib import Path

import pytest

from freepilot import ddcutil, displays, i2c, monitor
lazy from freepilot.vcp import Reading

TERSE = """\
VCP dc SNC x31
VCP 60 SNC x13
VCP 10 C 42 100
VCP 12 C 50 100
VCP 62 C 20 100
VCP 8d SNC x02
VCP e4 ERR
"""

CAPABILITIES = (
    "Unparsed capabilities string: "
    "(prot(monitor)type(LCD)model(RD280U)"
    "vcp(10 12 60(0F 11 13) 62 8D(01 02) DC(30 31)))"
)


class FakeRun:
    """Stand in for subprocess.run: record calls, answer getvcp from output."""

    def __init__(self, output: str = TERSE, returncode: int = 0) -> None:
        """Store the reply every call returns."""
        self.output = output
        self.capabilities = CAPABILITIES
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(
        self, command: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        """Record the command and return the canned reply."""
        self.calls.append(command)
        stdout = (
            self.output
            if "getvcp" in command
            else self.capabilities
            if "capabilities" in command
            else ""
        )
        stderr = "" if self.returncode == 0 else "Display not found"
        return subprocess.CompletedProcess(command, self.returncode, stdout, stderr)


@pytest.fixture(autouse=True)
def no_write_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the post-write sleeps in every test."""
    monkeypatch.setattr(monitor.time, "sleep", lambda _: None)
    monkeypatch.setattr(i2c.time, "sleep", lambda _: None)


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


# Calls in order: bare names, or (name, argument) pairs.
type Log = list[str | tuple[str, object]]


class FakeClock:
    """Record waits into a shared log and advance time by them."""

    def __init__(self, log: Log) -> None:
        """Start at zero."""
        self.now = 0.0
        self.log = log

    def monotonic(self) -> float:
        """Return the current fake time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance time and log the wait."""
        self.now += seconds
        self.log.append(("sleep", seconds))


class FakeDevice:
    """Answer reads from a script and log every call."""

    def __init__(
        self,
        log: Log,
        replies: list[bytes | OSError] | None = None,
        *,
        busy_polls: int = 0,
        write_error: OSError | None = None,
        short_write: bool = False,
    ) -> None:
        """Store the script."""
        self.log = log
        self.replies = list(replies or [])
        self.busy_polls = busy_polls
        self.write_error = write_error
        self.short_write = short_write

    def write(self, data: bytes) -> int:
        """Log the bytes written."""
        self.log.append(("write", data.hex(" ")))
        if self.write_error:
            raise self.write_error
        return len(data) - 1 if self.short_write else len(data)

    def read(self, size: int) -> bytes:
        """Return the next scripted reply."""
        self.log.append(("read", size))
        reply = self.replies.pop(0)
        if isinstance(reply, OSError):
            raise reply
        return reply

    def try_lock(self) -> bool:
        """Report the lock busy for the first busy_polls tries."""
        self.log.append("try_lock")
        if self.busy_polls:
            self.busy_polls -= 1
            return False
        return True

    def close(self) -> None:
        """Log the close."""
        self.log.append("close")


@pytest.fixture(autouse=True)
def sysfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give every test a fake sysfs and its own config path.

    The fake has a BenQ RD280U on bus 4 and an HDMI monitor with no bus or
    EDID, so tests never see the host's real monitors.
    """
    root = tmp_path / "drm"
    edid = make_edid(texts={0xFC: b"BenQ RD280U\n", 0xFF: b"ABC123\n"})
    make_connector(root, "card1-DP-1", edid=edid, ddc_bus=4)
    make_connector(root, "card1-HDMI-A-1")
    monkeypatch.setattr(displays, "DRM_ROOT", root)
    monkeypatch.setenv("FREEPILOT_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


class FakeTransport:
    """Answer reads from a fixed table and record writes."""

    def __init__(self, readings: dict[int, Reading] | None = None) -> None:
        """Store the readings that get returns."""
        self.readings = readings or {}
        self.writes: list[tuple[int, int]] = []
        self.log: list[str] = []

    @contextmanager
    def session(self) -> Generator[None]:
        """Record when the session opens and closes."""
        self.log.append("open")
        try:
            yield
        finally:
            self.log.append("close")

    def get(self, *codes: int) -> dict[int, Reading]:
        """Return the stored readings for the requested codes."""
        return {code: self.readings[code] for code in codes if code in self.readings}

    def set(self, code: int, value: int) -> None:
        """Record the write."""
        self.writes.append((code, value))
        self.log.append(f"set 0x{code:02x}")

    def capabilities(self) -> str:
        """Return a short capability string."""
        return "(vcp(10 60(0F 11)))"
