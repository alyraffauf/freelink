"""Shared fixtures: a fake ddcutil and no write delays."""

import subprocess

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
