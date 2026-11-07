use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Continuous,
    Choice,
    Raw,
}
#[derive(Clone, Debug, Serialize)]
pub struct Feature {
    pub name: &'static str,
    pub code: u8,
    pub description: &'static str,
    pub kind: Kind,
    pub values: &'static [(&'static str, u16)],
    pub values_confirmed: bool,
}
pub const PICTURE_MODES: &[(&str, u16)] = &[
    ("coding-light", 49),
    ("coding-dark", 48),
    ("coding-paper", 58),
    ("m-book", 15),
    ("cinema", 50),
    ("game", 40),
    ("epaper", 31),
    ("srgb", 10),
    ("user", 18),
    ("hdr", 35),
];
pub const MCCS_INPUTS: &[(&str, u16)] = &[
    ("d-sub", 1),
    ("d-sub2", 2),
    ("dvi", 3),
    ("dvi2", 4),
    ("displayport", 15),
    ("displayport2", 16),
    ("hdmi", 17),
    ("hdmi1", 17),
    ("hdmi2", 18),
];
pub const BENQ_INPUTS: &[(&str, u16)] = &[
    ("d-sub", 1),
    ("dvi", 3),
    ("displayport", 15),
    ("mini-displayport", 16),
    ("hdmi", 17),
    ("hdmi1", 17),
    ("hdmi2", 18),
    ("usb-c", 19),
    ("usb-c2", 20),
    ("thunderbolt", 21),
    ("hdmi3", 22),
];
pub const MUTE_STATES: &[(&str, u16)] = &[("on", 1), ("off", 2)];
// Wire values verified against Display Pilot 2 for Linux 1.1.4.0.
pub const COLOR_TEMPERATURES: &[(&str, u16)] =
    &[("5000k", 4), ("6500k", 5), ("9300k", 8), ("user", 11)];
pub const GAMMAS: &[(&str, u16)] = &[
    ("1.6", 60),
    ("1.8", 80),
    ("2.0", 100),
    ("srgb", 119),
    ("2.2", 120),
    ("2.4", 140),
    ("2.6", 160),
];
pub const NIGHT_STATES: &[(&str, u16)] = &[("off", 0), ("on", 1), ("auto", 2)];
pub const BI_STATES: &[(&str, u16)] = &[("off", 0), ("bi-plus", 1), ("bi", 2)];
pub const KVM_TARGETS: &[(&str, u16)] =
    &[("thunderbolt", 1), ("usb-b", 2), ("usb-c", 3), ("auto", 4)];
pub const GUI_LEVELS: &[(&str, &str)] = &[
    ("brightness", "Brightness"),
    ("contrast", "Contrast"),
    ("sharpness", "Sharpness"),
    ("volume", "Volume"),
    ("low-blue-light", "Low blue"),
    ("night-protection-level", "Night level"),
    ("red-gain", "Red"),
    ("green-gain", "Green"),
    ("blue-gain", "Blue"),
];
pub const EXTRA_CONTROLS: &[&str] = &[
    "sharpness",
    "low-blue-light",
    "night-protection",
    "night-protection-level",
    "bright-intelligence",
    "color-temperature",
    "gamma",
    "red-gain",
    "green-gain",
    "blue-gain",
    "kvm",
];

pub fn level_bounds(name: &str) -> (u16, u16) {
    match name {
        "low-blue-light" => (0, 5),
        "night-protection-level" => (1, 10),
        _ => (0, 100),
    }
}
pub fn slider_bounds(name: &str, maximum: Option<u16>) -> (u16, u16) {
    let (min, fallback) = level_bounds(name);
    let max = maximum
        .filter(|max| *max > min)
        .unwrap_or(fallback)
        .min(fallback);
    (min, max)
}
const BRIGHTNESS: Feature = Feature {
    name: "brightness",
    code: 0x10,
    description: "Brightness, 0-100",
    kind: Kind::Continuous,
    values: &[],
    values_confirmed: true,
};
const CONTRAST: Feature = Feature {
    name: "contrast",
    code: 0x12,
    description: "Contrast, 0-100",
    kind: Kind::Continuous,
    values: &[],
    values_confirmed: true,
};
const VOLUME: Feature = Feature {
    name: "volume",
    code: 0x62,
    description: "Speaker volume, 0-100",
    kind: Kind::Continuous,
    values: &[],
    values_confirmed: true,
};
const SHARPNESS: Feature = Feature {
    name: "sharpness",
    code: 0x87,
    description: "Sharpness",
    kind: Kind::Continuous,
    values: &[],
    values_confirmed: true,
};
const MUTE: Feature = Feature {
    name: "mute",
    code: 0x8D,
    description: "Audio mute",
    kind: Kind::Choice,
    values: MUTE_STATES,
    values_confirmed: true,
};

pub const MCCS_FEATURES: &[Feature] = &[
    BRIGHTNESS,
    CONTRAST,
    Feature {
        name: "input",
        code: 0x60,
        description: "Input source",
        kind: Kind::Choice,
        values: MCCS_INPUTS,
        values_confirmed: true,
    },
    VOLUME,
    SHARPNESS,
    MUTE,
];
pub const BENQ_RD_FEATURES: &[Feature] = &[
    BRIGHTNESS,
    CONTRAST,
    Feature {
        name: "color-temperature",
        code: 0x14,
        description: "Colour temperature preset",
        kind: Kind::Choice,
        values: COLOR_TEMPERATURES,
        values_confirmed: true,
    },
    Feature {
        name: "red-gain",
        code: 0x16,
        description: "Red gain",
        kind: Kind::Continuous,
        values: &[],
        values_confirmed: true,
    },
    Feature {
        name: "green-gain",
        code: 0x18,
        description: "Green gain",
        kind: Kind::Continuous,
        values: &[],
        values_confirmed: true,
    },
    Feature {
        name: "blue-gain",
        code: 0x1A,
        description: "Blue gain",
        kind: Kind::Continuous,
        values: &[],
        values_confirmed: true,
    },
    Feature {
        name: "low-blue-light",
        code: 0x19,
        description: "Low blue light level",
        kind: Kind::Continuous,
        values: &[],
        values_confirmed: true,
    },
    Feature {
        name: "gamut",
        code: 0x5F,
        description: "Colour gamut",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "input",
        code: 0x60,
        description: "Input source",
        kind: Kind::Choice,
        values: BENQ_INPUTS,
        values_confirmed: true,
    },
    VOLUME,
    Feature {
        name: "gamma",
        code: 0x72,
        description: "Gamma preset",
        kind: Kind::Choice,
        values: GAMMAS,
        values_confirmed: true,
    },
    Feature {
        name: "pip-pbp",
        code: 0x7D,
        description: "PIP/PBP mode",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "bright-intelligence",
        code: 0x81,
        description: "Bright Intelligence Plus",
        kind: Kind::Choice,
        values: BI_STATES,
        values_confirmed: true,
    },
    SHARPNESS,
    MUTE,
    Feature {
        name: "audio-mode",
        code: 0x94,
        description: "Audio mode",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "auto-pivot",
        code: 0xAA,
        description: "Auto pivot status",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "night-protection-level",
        code: 0xD0,
        description: "Night protection level",
        kind: Kind::Continuous,
        values: &[],
        values_confirmed: true,
    },
    Feature {
        name: "night-protection",
        code: 0xD1,
        description: "Night hours protection",
        kind: Kind::Choice,
        values: NIGHT_STATES,
        values_confirmed: true,
    },
    Feature {
        name: "power-mode",
        code: 0xD6,
        description: "Power mode",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: true,
    },
    Feature {
        name: "backlight",
        code: 0xD7,
        description: "Backlight switch",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "backlight-level",
        code: 0xD9,
        description: "Backlight level",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "picture-mode",
        code: 0xDC,
        description: "Picture mode",
        kind: Kind::Choice,
        values: PICTURE_MODES,
        values_confirmed: true,
    },
    Feature {
        name: "bi-sensor",
        code: 0xE2,
        description: "Bright Intelligence sensor",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "light-meter",
        code: 0xE3,
        description: "Light meter",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "kvm",
        code: 0xE4,
        description: "KVM switch",
        kind: Kind::Choice,
        values: KVM_TARGETS,
        values_confirmed: true,
    },
    Feature {
        name: "bi-sensitivity",
        code: 0xE5,
        description: "Bright Intelligence sensitivity",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "daisy-chain",
        code: 0xE6,
        description: "DisplayPort daisy chain",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "eco-privacy",
        code: 0xE7,
        description: "Eco privacy (MoonHalo) timer",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "eco-privacy-mode",
        code: 0xE8,
        description: "Eco privacy mode",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "eco-privacy-sensitivity",
        code: 0xE9,
        description: "Eco privacy sensor",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "ai-contrast",
        code: 0xF3,
        description: "AI contrast",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "dual-view",
        code: 0xF4,
        description: "Dual view",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "uniformity",
        code: 0xFA,
        description: "Uniformity",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
    Feature {
        name: "color-weakness",
        code: 0xFD,
        description: "Colour weakness filter",
        kind: Kind::Raw,
        values: &[],
        values_confirmed: false,
    },
];

pub fn features(benq: bool) -> &'static [Feature] {
    if benq {
        BENQ_RD_FEATURES
    } else {
        MCCS_FEATURES
    }
}
pub fn feature(benq: bool, name: &str) -> anyhow::Result<&'static Feature> {
    features(benq)
        .iter()
        .find(|feature| feature.name == name)
        .ok_or_else(|| anyhow::anyhow!("Unknown feature {name} for this monitor"))
}
/// Parses a decimal number or a `0x`-prefixed hexadecimal number.
pub fn number(text: &str) -> anyhow::Result<u16> {
    let parsed = match text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
        Some(digits) => u16::from_str_radix(digits, 16),
        None => text.parse(),
    };
    parsed.map_err(|_| anyhow::anyhow!("\"{text}\" is not a number"))
}
pub fn code(benq: bool, name: &str) -> anyhow::Result<u8> {
    if let Ok(feature) = feature(benq, name) {
        return Ok(feature.code);
    }
    Ok(u8::try_from(number(name)?)?)
}
/// Resolves a named setting to its VCP code and wire value.
///
/// Choice features take one of their labels. Continuous features take a number
/// within `level_bounds`. Raw features take any 16-bit number unchecked, since
/// their valid range is not known.
pub fn setting(benq: bool, name: &str, value: &str) -> anyhow::Result<(u8, u16)> {
    let feature = feature(benq, name)?;
    let value = match feature.kind {
        Kind::Choice => feature
            .values
            .iter()
            .find(|(label, _)| *label == value)
            .map(|(_, wire_value)| *wire_value)
            .ok_or_else(|| anyhow::anyhow!("Unknown {name} value {value}"))?,
        Kind::Continuous => {
            let value = number(value)?;
            let (min, max) = level_bounds(name);
            anyhow::ensure!(
                (min..=max).contains(&value),
                "{name} must be between {min} and {max}"
            );
            value
        }
        Kind::Raw => number(value)?,
    };
    Ok((feature.code, value))
}
pub fn write_delay(code: u8) -> u64 {
    match code {
        0xdc | 0x13 => 500,
        0x08 => 5000,
        0x04 => 2000,
        0x94 => 700,
        0xe4 => 1000,
        _ => 0,
    }
}
