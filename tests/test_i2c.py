"""Tests for the native DDC/CI transport, against a scripted device.

The packet vectors below were worked out by hand from VESA DDC/CI 1.1, not
produced by the encoder.
"""

import errno
lazy from collections.abc import Callable

import pytest
from conftest import FakeClock, FakeDevice, Log

from freepilot.i2c import (
    I2c,
    I2cError,
    MalformedReplyError,
    NullReplyError,
    Timing,
    decode_get_reply,
    encode_get,
    encode_set,
)
from freepilot.vcp import Reading

GET_BRIGHTNESS = "51 82 01 10 ac"
SET_BRIGHTNESS_50 = "51 84 03 10 00 32 9a"
BRIGHTNESS_50_OF_100 = bytes.fromhex("6e 88 02 00 10 00 00 64 00 32 f2")
KVM_UNSUPPORTED = bytes.fromhex("6e 88 02 01 e4 00 00 00 00 00 51")
NULL = bytes.fromhex("6e 80 be") + bytes(8)


def test_requests_match_the_spec() -> None:
    """Get and Set requests carry the host address, length, and checksum."""
    assert encode_get(0x10).hex(" ") == GET_BRIGHTNESS
    assert encode_set(0x10, 50).hex(" ") == SET_BRIGHTNESS_50


@pytest.mark.parametrize(("code", "value"), [(0x100, 0), (-1, 0), (0x10, 0x10000)])
def test_requests_refuse_numbers_that_do_not_fit(code: int, value: int) -> None:
    """Codes are one byte and values two."""
    with pytest.raises(I2cError, match="outside"):
        encode_set(code, value)


def test_reply_decodes_value_and_maximum() -> None:
    """A Get reply gives the current value and the maximum."""
    assert decode_get_reply(BRIGHTNESS_50_OF_100, 0x10) == Reading(0x10, 50, 100)


def test_reply_ignores_bytes_past_the_declared_length() -> None:
    """An oversized read still decodes; the length byte says where to stop."""
    assert decode_get_reply(BRIGHTNESS_50_OF_100 + b"\xff\xff", 0x10).value == 50


def test_unsupported_code_reads_as_none() -> None:
    """Result 1 means the monitor does not support the code."""
    assert decode_get_reply(KVM_UNSUPPORTED, 0xE4) == Reading(0xE4, None)


def test_null_message_is_found_inside_a_full_read() -> None:
    """The three-byte null message is recognised in an 11-byte read."""
    with pytest.raises(NullReplyError):
        decode_get_reply(NULL, 0x10)


def with_checksum(body: str) -> bytes:
    """Append the reply checksum to hand-written bytes."""
    data = bytes.fromhex(body)
    total = 0x50
    for byte in data:
        total ^= byte
    return data + bytes([total])


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\x6e\x88", "2 bytes"),
        (with_checksum("6f 88 02 00 10 00 00 64 00 32"), "comes from 0x6f"),
        (with_checksum("6e 08 02 00 10 00 00 64 00 32"), "lacks the length flag"),
        (BRIGHTNESS_50_OF_100[:9], "declares 8 bytes but only 6"),
        (BRIGHTNESS_50_OF_100[:-1] + b"\x00", "checksum"),
        (with_checksum("6e 88 03 00 10 00 00 64 00 32"), "expected a Get VCP reply"),
        (with_checksum("6e 83 02 00 10"), "expected a Get VCP reply"),
        (with_checksum("6e 88 02 00 12 00 00 64 00 32"), "reply is for 0x12"),
        (with_checksum("6e 88 02 05 10 00 00 64 00 32"), "result code 5"),
    ],
)
def test_malformed_replies_are_rejected(data: bytes, message: str) -> None:
    """Every part of the envelope is checked before the result is used."""
    with pytest.raises(MalformedReplyError, match=message):
        decode_get_reply(data, 0x10)


def transport(device: FakeDevice, log: Log) -> I2c:
    """Build an I2c transport on bus 4 with the fake device and clock."""
    opened: list[int] = []

    def open_device(bus: int) -> FakeDevice:
        opened.append(bus)
        log.append(("open", bus))
        return device

    return I2c(4, open_device=open_device, clock=FakeClock(log))


def test_get_writes_waits_and_reads_once_under_the_lock() -> None:
    """One attempt is a write, a 40 ms wait, and one 11-byte read."""
    log: Log = []
    device = FakeDevice(log, [BRIGHTNESS_50_OF_100])
    assert transport(device, log).get(0x10) == {0x10: Reading(0x10, 50, 100)}
    assert log == [
        ("open", 4),
        "try_lock",
        ("write", GET_BRIGHTNESS),
        ("sleep", 0.04),
        ("read", 11),
        "close",
    ]


def test_get_retries_with_longer_waits() -> None:
    """A null reply resends the whole request and waits longer."""
    log: Log = []
    device = FakeDevice(log, [NULL, BRIGHTNESS_50_OF_100])
    assert transport(device, log).get(0x10)[0x10].value == 50
    assert [entry for entry in log if entry[0] in {"write", "sleep"}] == [
        ("write", GET_BRIGHTNESS),
        ("sleep", 0.04),
        ("write", GET_BRIGHTNESS),
        ("sleep", 0.08),
    ]


def test_persistent_null_reads_as_none() -> None:
    """After every try returns null, the code is unreadable, not an error."""
    log: Log = []
    device = FakeDevice(log, [NULL] * 4)
    assert transport(device, log).get(0x10) == {0x10: Reading(0x10, None)}
    assert log.count(("read", 11)) == len(Timing().get_waits)


def test_persistent_malformed_reply_is_raised_and_the_bus_closed() -> None:
    """A bad reply on the last try is an error, and the device still closes."""
    log: Log = []
    bad = BRIGHTNESS_50_OF_100[:-1] + b"\x00"
    device = FakeDevice(log, [NULL, NULL, NULL, bad])
    with pytest.raises(MalformedReplyError):
        transport(device, log).get(0x10)
    assert log[-1] == "close"


def test_no_acknowledgement_is_retried_then_explained() -> None:
    """ENXIO is retried like a bad reply, then reported plainly."""
    log: Log = []
    nack = OSError(errno.ENXIO, "No such device or address")
    device = FakeDevice(log, [nack, BRIGHTNESS_50_OF_100])
    assert transport(device, log).get(0x10)[0x10].value == 50
    device = FakeDevice(log, [nack] * 4)
    with pytest.raises(I2cError, match="no DDC/CI answer on i2c-4"):
        transport(device, log).get(0x10)


def test_unplugged_bus_is_explained() -> None:
    """ENODEV means the bus went away."""
    log: Log = []
    device = FakeDevice(log, [OSError(errno.ENODEV, "No such device")] * 4)
    with pytest.raises(I2cError, match="i2c-4 went away"):
        transport(device, log).get(0x10)
    assert log[-1] == "close"


def test_set_writes_once_then_waits() -> None:
    """A write is one message followed by the 50 ms wait."""
    log: Log = []
    transport(FakeDevice(log), log).set(0x10, 50)
    assert log == [
        ("open", 4),
        "try_lock",
        ("write", SET_BRIGHTNESS_50),
        ("sleep", 0.05),
        "close",
    ]


@pytest.mark.parametrize(
    ("make_device", "message"),
    [
        (
            lambda log: FakeDevice(log, write_error=OSError(errno.ENXIO, "nack")),
            "no DDC/CI answer",
        ),
        (lambda log: FakeDevice(log, short_write=True), "wrote 6 of 7 bytes"),
    ],
)
def test_failed_set_is_never_resent(
    make_device: Callable[[Log], FakeDevice], message: str
) -> None:
    """A write that fails is reported once, because it may have applied."""
    log: Log = []
    device = make_device(log)
    with pytest.raises(I2cError, match=message):
        transport(device, log).set(0x10, 50)
    assert [entry for entry in log if entry[0] == "write"] == [
        ("write", SET_BRIGHTNESS_50)
    ]
    assert log[-1] == "close"


def test_lock_waits_then_succeeds() -> None:
    """A busy lock is polled until it frees up."""
    log: Log = []
    device = FakeDevice(log, [BRIGHTNESS_50_OF_100], busy_polls=2)
    transport(device, log).get(0x10)
    assert log[1:6] == [
        "try_lock",
        ("sleep", 0.05),
        "try_lock",
        ("sleep", 0.05),
        "try_lock",
    ]


def test_lock_gives_up_at_the_deadline() -> None:
    """A lock held for longer than the timeout is an error, and nothing is sent."""
    log: Log = []
    device = FakeDevice(log, busy_polls=1000)
    with pytest.raises(I2cError, match="i2c-4 is busy"):
        transport(device, log).get(0x10)
    assert not any(entry[0] == "write" for entry in log)
    assert log[-1] == "close"


def test_nested_sessions_share_one_open_and_lock() -> None:
    """Reads and writes inside an outer session reuse its device."""
    log: Log = []
    device = FakeDevice(log, [BRIGHTNESS_50_OF_100])
    bus = transport(device, log)
    with bus.session():
        bus.get(0x10)
        bus.set(0x10, 50)
    assert log.count(("open", 4)) == 1
    assert log.count("close") == 1


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (PermissionError(errno.EACCES, "denied"), "no access to /dev/i2c-4"),
        (FileNotFoundError(errno.ENOENT, "missing"), "is the i2c-dev module loaded"),
        (OSError(errno.EBUSY, "Device or resource busy"), "can't open /dev/i2c-4"),
    ],
)
def test_open_failures_are_explained(error: OSError, message: str) -> None:
    """Opening the bus fails with a message that says what to fix."""

    def open_device(_: int) -> FakeDevice:
        raise error

    with pytest.raises(I2cError, match=message):
        I2c(4, open_device=open_device).get(0x10)
