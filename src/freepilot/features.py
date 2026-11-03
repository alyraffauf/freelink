"""VCP features: a standard MCCS set, and the BenQ RD set.

The BenQ tables come from Display Pilot 2 for Linux 1.1.4.0. None of them
has been tried on a monitor yet. See NOTES.md for the source of each table.
Monitors that aren't identified as BenQ RD get only the standard set, so
BenQ's value names are never applied to other monitors.
"""

import re
from dataclasses import dataclass
from typing import Literal

type NameTable = frozendict[str, int]

# How to show a value: continuous as current/max, choice by name from the
# feature's value table, raw in hex.
type FeatureKind = Literal["continuous", "choice", "raw"]

# Picture modes write (SHCode << 8) | Code to VCP 0xDC, using the Code and
# SHCode attributes from each model's RDxxxx.xml. Every RD model uses SHCode
# 0, so the value is the mode code.
PICTURE_MODES: NameTable = frozendict(
    {
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
)

# Input source values from the MCCS standard. Vendors define the rest.
MCCS_INPUTS: NameTable = frozendict(
    {
        "d-sub": 0x01,
        "d-sub2": 0x02,
        "dvi": 0x03,
        "dvi2": 0x04,
        "displayport": 0x0F,
        "displayport2": 0x10,
        "hdmi": 0x11,
        "hdmi1": 0x11,
        "hdmi2": 0x12,
    }
)

# BenQ's values for VCP 0x60. Where two names share a value, the first is the
# one freepilot displays. BenQ uses 0x13 for USB-C.
BENQ_INPUTS: NameTable = frozendict(
    {
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
)

MUTE_STATES: NameTable = frozendict({"on": 1, "off": 2})

MAX_LEVEL = 100


@dataclass(frozen=True, slots=True)
class Feature:
    """A VCP code that Display Pilot 2 reads or writes."""

    code: int
    description: str
    kind: FeatureKind = "raw"
    # Names for a choice feature's values.
    values: NameTable = frozendict()
    # False when the code is confirmed but what its values mean is not.
    values_confirmed: bool = True


# Standard MCCS controls, safe to use on any monitor.
MCCS_FEATURES: frozendict[str, Feature] = frozendict(
    {
        "brightness": Feature(0x10, "Brightness, 0-100", "continuous"),
        "contrast": Feature(0x12, "Contrast, 0-100", "continuous"),
        "input": Feature(0x60, "Input source", "choice", MCCS_INPUTS),
        "volume": Feature(0x62, "Speaker volume, 0-100", "continuous"),
        "sharpness": Feature(0x87, "Sharpness", "continuous"),
        "mute": Feature(0x8D, "Audio mute", "choice", MUTE_STATES),
    }
)

BENQ_RD_FEATURES: frozendict[str, Feature] = frozendict(
    {
        "brightness": Feature(0x10, "Brightness, 0-100", "continuous"),
        "contrast": Feature(0x12, "Contrast, 0-100", "continuous"),
        "color-temperature": Feature(
            0x14, "Colour temperature preset", values_confirmed=False
        ),
        "red-gain": Feature(0x16, "Red gain", values_confirmed=False),
        "green-gain": Feature(0x18, "Green gain", values_confirmed=False),
        "blue-gain": Feature(0x1A, "Blue gain", values_confirmed=False),
        "low-blue-light": Feature(0x19, "Low blue light level", values_confirmed=False),
        "gamut": Feature(0x5F, "Colour gamut", values_confirmed=False),
        "input": Feature(0x60, "Input source", "choice", BENQ_INPUTS),
        "volume": Feature(0x62, "Speaker volume, 0-100", "continuous"),
        "gamma": Feature(0x72, "Gamma preset", values_confirmed=False),
        "pip-pbp": Feature(0x7D, "PIP/PBP mode", values_confirmed=False),
        "bright-intelligence": Feature(
            0x81, "Bright Intelligence Plus", values_confirmed=False
        ),
        "sharpness": Feature(0x87, "Sharpness", "continuous"),
        "mute": Feature(0x8D, "Audio mute", "choice", MUTE_STATES),
        "audio-mode": Feature(0x94, "Audio mode", values_confirmed=False),
        "auto-pivot": Feature(0xAA, "Auto pivot status", values_confirmed=False),
        "night-protection-level": Feature(
            0xD0, "Night protection level", values_confirmed=False
        ),
        "night-protection": Feature(
            0xD1, "Night hours protection", values_confirmed=False
        ),
        "power-mode": Feature(0xD6, "Power mode"),
        "backlight": Feature(0xD7, "Backlight switch", values_confirmed=False),
        "backlight-level": Feature(0xD9, "Backlight level", values_confirmed=False),
        "picture-mode": Feature(0xDC, "Picture mode", "choice", PICTURE_MODES),
        "bi-sensor": Feature(
            0xE2, "Bright Intelligence sensor", values_confirmed=False
        ),
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
        "color-weakness": Feature(
            0xFD, "Colour weakness filter", values_confirmed=False
        ),
    }
)

# Display Pilot 2 waits this long, in milliseconds, after writing these codes.
WRITE_DELAYS: frozendict[int, int] = frozendict(
    {0xDC: 500, 0x08: 5000, 0x04: 2000, 0x94: 700, 0xE4: 1000, 0x13: 500}
)


@dataclass(frozen=True, slots=True)
class FeatureSet:
    """The features freepilot uses for one kind of monitor.

    status lists the features freepilot status reads, in order.
    """

    name: str
    description: str
    features: frozendict[str, Feature]
    status: tuple[str, ...]

    def feature_name(self, code: int) -> str | None:
        """Return the feature name for a VCP code, if this set has one."""
        return next(
            (name for name, feature in self.features.items() if feature.code == code),
            None,
        )

    def feature_for(self, code: int) -> Feature | None:
        """Return the feature for a VCP code, if this set has one."""
        name = self.feature_name(code)
        return self.features[name] if name else None

    def values(self, name: str) -> NameTable:
        """Return a choice feature's value names, or an empty table."""
        feature = self.features.get(name)
        return feature.values if feature else frozendict()


MCCS = FeatureSet(
    "mccs",
    "Standard MCCS controls",
    MCCS_FEATURES,
    ("input", "brightness", "contrast", "volume", "mute"),
)
BENQ_RD = FeatureSet(
    "benq-rd",
    "BenQ RD series",
    BENQ_RD_FEATURES,
    ("picture-mode", "input", "brightness", "contrast", "volume", "mute"),
)
FEATURE_SETS: frozendict[str, FeatureSet] = frozendict(
    {feature_set.name: feature_set for feature_set in (BENQ_RD, MCCS)}
)
# Matches EDID model names such as "BenQ RD280U" or "RD240Q".
BENQ_RD_MODEL = re.compile(r"(?:^|\s)RD\d")


def identify(manufacturer: str | None, model: str | None) -> FeatureSet:
    """Pick the feature set for a monitor from its EDID identity.

    This is a heuristic. A BenQ (BNQ) monitor whose model name starts with RD
    gets the BenQ set. Everything else, including monitors with no EDID, gets
    the standard set. --model overrides it.
    """
    if manufacturer == "BNQ" and model and BENQ_RD_MODEL.search(model):
        return BENQ_RD
    return MCCS


def name_for(table: NameTable, value: int) -> str | None:
    """Return the first name for a value in a name table, if any."""
    return next((name for name, candidate in table.items() if candidate == value), None)
