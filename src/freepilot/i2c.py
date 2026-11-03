"""Talk DDC/CI to a monitor directly through /dev/i2c-N.

Packets follow VESA DDC/CI 1.1. The byte handling is pure functions. The
I2c transport adds retries, waits, and the bus lock on top of a Device,
and LinuxDevice is the only part that makes system calls.

Nothing here has run against a monitor yet, which is why ddcutil stays the
default transport.
"""

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import reduce
from typing import Protocol, Self
lazy from collections.abc import Callable, Generator

from freepilot.vcp import Reading, TransportError

DDC_ADDRESS = 0x37
I2C_SLAVE = 0x0703  # ioctl that sets the address later reads and writes use
HOST = 0x51  # the source address the host writes first in every request
DISPLAY = 0x6E  # the source address that starts every reply
REQUEST_SEED = 0x6E  # requests checksum the display's write address first
REPLY_SEED = 0x50  # replies checksum the host's virtual address first
LENGTH_FLAG = 0x80
GET_REQUEST, GET_REPLY, SET_REQUEST = 0x01, 0x02, 0x03
GET_REPLY_SIZE = 11
MAX_CODE, MAX_VALUE = 0xFF, 0xFFFF
# I/O errors that mean the monitor did not acknowledge, so a retry may help.
NO_ANSWER = frozenset({errno.ENXIO, errno.EREMOTEIO, errno.EIO, errno.EAGAIN})


class I2cError(TransportError):
    """The bus could not be used, or the monitor's reply could not be used."""


class NullReplyError(I2cError):
    """The monitor sent the null message: busy, or not supported. Ambiguous."""


class MalformedReplyError(I2cError):
    """A reply with the wrong framing, opcode, code, or checksum."""


def checksum(seed: int, data: bytes) -> int:
    """XOR a seed with every byte."""
    return reduce(lambda total, byte: total ^ byte, data, seed)


def encode(payload: bytes) -> bytes:
    """Frame a request payload: host address, length, payload, checksum."""
    body = bytes([HOST, LENGTH_FLAG | len(payload), *payload])
    return body + bytes([checksum(REQUEST_SEED, body)])


def encode_get(code: int) -> bytes:
    """Build a Get VCP Feature request."""
    check_range("VCP code", code, MAX_CODE)
    return encode(bytes([GET_REQUEST, code]))


def encode_set(code: int, value: int) -> bytes:
    """Build a Set VCP Feature request. The value is 16 bits, big-endian."""
    check_range("VCP code", code, MAX_CODE)
    check_range("value", value, MAX_VALUE)
    return encode(bytes([SET_REQUEST, code, *value.to_bytes(2, "big")]))


def check_range(what: str, number: int, maximum: int) -> None:
    """Refuse numbers that don't fit the packet field."""
    if not 0 <= number <= maximum:
        message = f"{what} {number} is outside 0-{maximum}"
        raise I2cError(message)


def decode_frame(data: bytes) -> bytes:
    """Check a reply's framing and return its payload.

    The declared length decides where the checksum is, so bytes past it in
    an oversized read are ignored. An empty payload is the null message.
    """
    if len(data) < 3:  # noqa: PLR2004 - source, length, and checksum
        message = f"reply is {len(data)} bytes"
        raise MalformedReplyError(message)
    if data[0] != DISPLAY:
        message = f"reply comes from 0x{data[0]:02x}, not 0x{DISPLAY:02x}"
        raise MalformedReplyError(message)
    if not data[1] & LENGTH_FLAG:
        message = f"reply length byte 0x{data[1]:02x} lacks the length flag"
        raise MalformedReplyError(message)
    end = 2 + (data[1] & ~LENGTH_FLAG)
    if len(data) <= end:
        message = f"reply declares {end - 2} bytes but only {len(data) - 3} came"
        raise MalformedReplyError(message)
    if checksum(REPLY_SEED, data[:end]) != data[end]:
        message = "reply checksum does not match"
        raise MalformedReplyError(message)
    if end == 2:  # noqa: PLR2004 - no payload
        message = "monitor sent the null message"
        raise NullReplyError(message)
    return data[2:end]


def decode_get_reply(data: bytes, code: int) -> Reading:
    """Turn a Get VCP Feature reply into a reading.

    A code the monitor reports as unsupported reads as None.
    """
    payload = decode_frame(data)
    if payload[0] != GET_REPLY or len(payload) != GET_REPLY_SIZE - 3:
        message = f"expected a Get VCP reply, got {payload.hex(' ')}"
        raise MalformedReplyError(message)
    _, result, echoed, _kind, max_high, max_low, high, low = payload
    if echoed != code:
        message = f"asked for 0x{code:02x}, reply is for 0x{echoed:02x}"
        raise MalformedReplyError(message)
    match result:
        case 0x00:
            return Reading(code, high << 8 | low, max_high << 8 | max_low)
        case 0x01:
            return Reading(code, None)
        case _:
            message = f"reply result code {result} is not 0 or 1"
            raise MalformedReplyError(message)


class Device(Protocol):
    """An open i2c device already pointed at the DDC/CI address."""

    def write(self, data: bytes) -> int:
        """Write one i2c message and return how many bytes went out."""
        ...

    def read(self, size: int) -> bytes:
        """Read one i2c message of up to size bytes."""
        ...

    def try_lock(self) -> bool:
        """Take the exclusive bus lock if it is free, without waiting."""
        ...

    def close(self) -> None:
        """Close the device, which also releases the lock."""
        ...


class Clock(Protocol):
    """Time, so tests can run waits instantly and check them."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary start."""
        ...

    def sleep(self, seconds: float) -> None:
        """Wait."""
        ...


class SystemClock:
    """The real clock."""

    def monotonic(self) -> float:
        """Return time.monotonic()."""
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        """Call time.sleep()."""
        time.sleep(seconds)


@dataclass(frozen=True, slots=True)
class LinuxDevice:
    """/dev/i2c-N through os.read, os.write, ioctl, and flock."""

    fd: int

    @classmethod
    def open(cls, bus: int) -> Self:
        """Open /dev/i2c-N and point it at the DDC/CI address."""
        fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, DDC_ADDRESS)
        except OSError:
            os.close(fd)
            raise
        return cls(fd)

    def write(self, data: bytes) -> int:
        """Write one message."""
        return os.write(self.fd, data)

    def read(self, size: int) -> bytes:
        """Read one message."""
        return os.read(self.fd, size)

    def try_lock(self) -> bool:
        """Flock without blocking, as ddcutil does."""
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def close(self) -> None:
        """Close the descriptor."""
        os.close(self.fd)


@dataclass(frozen=True, slots=True)
class Timing:
    """Waits, in seconds. Conservative until measured on a monitor.

    get_waits is the wait before reading each attempt's reply: the first try
    and then each retry, which waits longer.
    """

    get_waits: tuple[float, ...] = (0.04, 0.08, 0.12, 0.2)
    set_wait: float = 0.05
    lock_timeout: float = 2.0
    lock_poll: float = 0.05


class I2c:
    """A Transport that speaks DDC/CI on one /dev/i2c-N bus."""

    def __init__(
        self,
        bus: int,
        *,
        open_device: Callable[[int], Device] | None = None,
        clock: Clock | None = None,
        timing: Timing | None = None,
    ) -> None:
        """Remember the bus. Nothing is opened until a session starts."""
        self.bus = bus
        self.open_device = open_device or LinuxDevice.open
        self.clock = clock or SystemClock()
        self.timing = timing or Timing()
        self.device: Device | None = None

    @contextmanager
    def session(self) -> Generator[None]:
        """Open and lock the bus until the block ends. Nested sessions share it."""
        if self.device is not None:
            yield
            return
        device = self.open()
        try:
            self.lock(device)
            self.device = device
            yield
        finally:
            self.device = None
            device.close()

    def get(self, *codes: int) -> dict[int, Reading]:
        """Read codes one after another under one lock."""
        requests = {code: encode_get(code) for code in codes}
        with self.session():
            return {
                code: self.get_one(code, request) for code, request in requests.items()
            }

    def set(self, code: int, value: int) -> None:
        """Write one code. A failed write is reported, never resent.

        The monitor sends no reply to a write, so after a failure freepilot
        can't know whether it took effect.
        """
        request = encode_set(code, value)
        with self.session():
            self.write(request)
            self.clock.sleep(self.timing.set_wait)

    def get_one(self, code: int, request: bytes) -> Reading:
        """Send a request until a usable reply comes back or tries run out.

        If every try gets the null message, the reading is None: the monitor
        may be busy or may not support the code, and freepilot can't tell.
        Other failures on the last try are raised.
        """
        failure: I2cError | None = None
        for wait in self.timing.get_waits:
            try:
                self.write(request)
                self.clock.sleep(wait)
                return decode_get_reply(self.read(GET_REPLY_SIZE), code)
            except NullReplyError:
                failure = None
            except I2cError as error:
                failure = error
        if failure is not None:
            raise failure
        return Reading(code, None)

    def open(self) -> Device:
        """Open the bus, explaining the usual reasons it fails."""
        path = f"/dev/i2c-{self.bus}"
        try:
            return self.open_device(self.bus)
        except PermissionError:
            message = f"no access to {path}; see the README for i2c permissions"
        except FileNotFoundError:
            message = f"{path} does not exist; is the i2c-dev module loaded?"
        except OSError as error:
            message = f"can't open {path}: {error.strerror}"
        raise I2cError(message)

    def lock(self, device: Device) -> None:
        """Take the bus lock, giving up after timing.lock_timeout."""
        deadline = self.clock.monotonic() + self.timing.lock_timeout
        while not device.try_lock():
            if self.clock.monotonic() >= deadline:
                message = f"i2c-{self.bus} is busy; another program holds its lock"
                raise I2cError(message)
            self.clock.sleep(self.timing.lock_poll)

    def write(self, data: bytes) -> None:
        """Write one message to the open device."""
        sent = self.call(lambda device: device.write(data))
        if sent != len(data):
            message = f"wrote {sent} of {len(data)} bytes to i2c-{self.bus}"
            raise I2cError(message)

    def read(self, size: int) -> bytes:
        """Read one message from the open device."""
        return self.call(lambda device: device.read(size))

    def call[T](self, operation: Callable[[Device], T]) -> T:
        """Run a device operation, turning OSError into I2cError."""
        if self.device is None:
            message = "i2c device used outside a session"
            raise RuntimeError(message)
        try:
            return operation(self.device)
        except OSError as error:
            if error.errno in NO_ANSWER:
                message = f"no DDC/CI answer on i2c-{self.bus} ({error.strerror})"
            elif error.errno == errno.ENODEV:
                message = f"i2c-{self.bus} went away"
            else:
                message = f"i2c-{self.bus}: {error.strerror}"
            raise I2cError(message) from error
