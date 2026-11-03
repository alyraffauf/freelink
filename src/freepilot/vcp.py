"""Raw VCP readings and the interface every transport provides."""

from dataclasses import dataclass
from typing import Protocol
lazy from contextlib import AbstractContextManager


class TransportError(Exception):
    """The monitor could not be reached, or its answer could not be used."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One VCP reading. value is None when the monitor did not answer.

    maximum is whatever the transport reported. Only continuous features
    give it a meaning.
    """

    code: int
    value: int | None
    maximum: int | None = None


class Transport(Protocol):
    """Reads and writes raw VCP codes on one monitor."""

    def session(self) -> AbstractContextManager[None]:
        """Hold the monitor for a sequence of reads, writes, and waits."""
        ...

    def get(self, *codes: int) -> dict[int, Reading]:
        """Read one or more VCP codes."""
        ...

    def set(self, code: int, value: int) -> None:
        """Write one VCP code."""
        ...
