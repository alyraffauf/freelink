"""VCP features of BenQ RD series monitors.

These tables come from Display Pilot 2 for Linux 1.1.4.0. None of them has
been tried on a monitor yet. See NOTES.md for the source of each table.
"""

from dataclasses import dataclass

# Picture modes write (SHCode << 8) | Code to VCP 0xDC, using the Code and
# SHCode attributes from each model's RDxxxx.xml. Every RD model uses SHCode
# 0, so the value is the mode code.
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

# Values for VCP 0x60. Where two names share a value, the first is the one
# freelink displays.
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

MAX_LEVEL = 100
MUTED, UNMUTED = 1, 2


@dataclass(frozen=True)
class Feature:
    """A VCP code that Display Pilot 2 reads or writes."""

    code: int
    description: str
    # False when the code is confirmed but what its values mean is not.
    values_confirmed: bool = True


FEATURES = {
    "brightness": Feature(0x10, "Brightness, 0-100"),
    "contrast": Feature(0x12, "Contrast, 0-100"),
    "color-temperature": Feature(
        0x14, "Colour temperature preset", values_confirmed=False
    ),
    "red-gain": Feature(0x16, "Red gain", values_confirmed=False),
    "green-gain": Feature(0x18, "Green gain", values_confirmed=False),
    "blue-gain": Feature(0x1A, "Blue gain", values_confirmed=False),
    "low-blue-light": Feature(0x19, "Low blue light level", values_confirmed=False),
    "gamut": Feature(0x5F, "Colour gamut", values_confirmed=False),
    "input": Feature(0x60, "Input source"),
    "volume": Feature(0x62, "Speaker volume, 0-100"),
    "gamma": Feature(0x72, "Gamma preset", values_confirmed=False),
    "pip-pbp": Feature(0x7D, "PIP/PBP mode", values_confirmed=False),
    "bright-intelligence": Feature(
        0x81, "Bright Intelligence Plus", values_confirmed=False
    ),
    "sharpness": Feature(0x87, "Sharpness"),
    "mute": Feature(0x8D, "Audio mute, 1 muted, 2 unmuted"),
    "audio-mode": Feature(0x94, "Audio mode", values_confirmed=False),
    "auto-pivot": Feature(0xAA, "Auto pivot status", values_confirmed=False),
    "night-protection-level": Feature(
        0xD0, "Night protection level", values_confirmed=False
    ),
    "night-protection": Feature(0xD1, "Night hours protection", values_confirmed=False),
    "power-mode": Feature(0xD6, "Power mode"),
    "backlight": Feature(0xD7, "Backlight switch", values_confirmed=False),
    "backlight-level": Feature(0xD9, "Backlight level", values_confirmed=False),
    "picture-mode": Feature(0xDC, "Picture mode"),
    "bi-sensor": Feature(0xE2, "Bright Intelligence sensor", values_confirmed=False),
    "light-meter": Feature(0xE3, "Light meter", values_confirmed=False),
    "kvm": Feature(0xE4, "KVM switch", values_confirmed=False),
    "bi-sensitivity": Feature(
        0xE5, "Bright Intelligence sensitivity", values_confirmed=False
    ),
    "daisy-chain": Feature(0xE6, "DisplayPort daisy chain", values_confirmed=False),
    "eco-privacy": Feature(
        0xE7, "Eco privacy (MoonHalo) timer", values_confirmed=False
    ),
    "eco-privacy-mode": Feature(0xE8, "Eco privacy mode", values_confirmed=False),
    "eco-privacy-sensitivity": Feature(
        0xE9, "Eco privacy sensor", values_confirmed=False
    ),
    "ai-contrast": Feature(0xF3, "AI contrast", values_confirmed=False),
    "dual-view": Feature(0xF4, "Dual view", values_confirmed=False),
    "uniformity": Feature(0xFA, "Uniformity", values_confirmed=False),
    "color-weakness": Feature(0xFD, "Colour weakness filter", values_confirmed=False),
}

# Display Pilot 2 waits this long, in milliseconds, after writing these codes.
WRITE_DELAYS = {0xDC: 500, 0x08: 5000, 0x04: 2000, 0x94: 700, 0xE4: 1000, 0x13: 500}


def name_for(table: dict[str, int], value: int) -> str | None:
    """Return the first name for a value in a name table, if any."""
    return next((name for name, candidate in table.items() if candidate == value), None)


def feature_name(code: int) -> str | None:
    """Return the feature name for a VCP code, if freelink knows it."""
    return next(
        (name for name, feature in FEATURES.items() if feature.code == code), None
    )
