"""Monitor operations, independent of how freepilot talks to the monitor."""

import time
from dataclasses import dataclass
lazy from collections.abc import Callable

from freepilot.capabilities import parse_capabilities
from freepilot.errors import FreepilotError
from freepilot.features import BENQ_RD, MUTE_STATES, WRITE_DELAYS, FeatureSet
lazy from freepilot.capabilities import Capabilities
lazy from freepilot.vcp import Reading, Transport

# Called before every write with the code and value; raises to refuse it.
type WriteCheck = Callable[[int, int], None]


class UnsupportedError(FreepilotError):
    """A named feature or value this monitor's feature set doesn't have."""


@dataclass(frozen=True, slots=True)
class Monitor:
    """A monitor reached through a transport, described by a feature set."""

    transport: Transport
    features: FeatureSet = BENQ_RD
    check: WriteCheck | None = None

    def read(self, *codes: int) -> dict[int, Reading]:
        """Read raw VCP codes."""
        with self.transport.session():
            return self.transport.get(*codes)

    def write(self, code: int, value: int) -> None:
        """Write a raw VCP code, then wait as long as Display Pilot 2 does.

        The wait happens inside the session, so nothing else uses the bus
        while the monitor settles.
        """
        if self.check is not None:
            self.check(code, value)
        with self.transport.session():
            self.transport.set(code, value)
            time.sleep(WRITE_DELAYS.get(code, 0) / 1000)

    def capabilities(self) -> Capabilities:
        """Fetch and parse the monitor's capability string."""
        with self.transport.session():
            return parse_capabilities(self.transport.capabilities())

    def status(self) -> dict[str, Reading | None]:
        """Read the feature set's status features, keyed by feature name.

        Readings stay raw. Naming their values is left to whoever shows them.
        """
        codes = {name: self.code(name) for name in self.features.status}
        readings = self.read(*codes.values())
        return {name: readings.get(code) for name, code in codes.items()}

    def code(self, feature: str) -> int:
        """Return a named feature's code, if this monitor's set has it."""
        found = self.features.features.get(feature)
        if found is None:
            message = (
                f"{feature} isn't available for {self.features.description}"
                " monitors; pass --model if this monitor is misidentified"
            )
            raise UnsupportedError(message)
        return found.code

    def choice(self, feature: str, name: str) -> tuple[int, int]:
        """Return the code and value for a named choice."""
        code = self.code(feature)
        values = self.features.values(feature)
        if name not in values:
            message = (
                f"{name} isn't a known {feature} for {self.features.description}"
                f" monitors; choose from {', '.join(values)}"
            )
            raise UnsupportedError(message)
        return code, values[name]

    def set_picture_mode(self, name: str) -> None:
        """Switch to a named picture mode."""
        self.write(*self.choice("picture-mode", name))

    def set_input(self, name: str) -> None:
        """Switch to a named input source."""
        self.write(*self.choice("input", name))

    def set_level(self, feature: str, value: int) -> None:
        """Set a 0-100 level such as brightness, contrast, or volume."""
        self.write(self.code(feature), value)

    def set_muted(self, *, muted: bool) -> None:
        """Mute or unmute the speakers."""
        self.write(self.code("mute"), MUTE_STATES["on" if muted else "off"])
