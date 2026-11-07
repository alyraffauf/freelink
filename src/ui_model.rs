use anyhow::{Result, bail};
use freepilot::{Status, capabilities::Capabilities, features};

#[derive(Clone, Debug, PartialEq)]
pub struct Choice {
    pub name: String,
    pub label: String,
    pub value: u16,
}
pub fn label(name: &str) -> String {
    match name {
        "coding-light" => "Coding · Light",
        "coding-dark" => "Coding · Dark",
        "coding-paper" => "Coding · Paper",
        "m-book" => "M-book",
        "epaper" => "ePaper",
        "srgb" => "sRGB",
        "hdr" => "HDR",
        "displayport" => "DisplayPort",
        "displayport2" => "DisplayPort 2",
        "mini-displayport" => "Mini DisplayPort",
        "hdmi" | "hdmi1" => "HDMI",
        "hdmi2" => "HDMI 2",
        "hdmi3" => "HDMI 3",
        "usb-c" => "USB-C",
        "usb-b" => "USB-B",
        "bi-plus" => "B.I.+",
        "bi" => "B.I.",
        "5000k" => "5000 K",
        "6500k" => "6500 K",
        "9300k" => "9300 K",
        "usb-c2" => "USB-C 2",
        "dvi" => "DVI",
        "d-sub" => "VGA",
        "kvm" => "KVM",
        _ => {
            return name
                .split('-')
                .map(|word| {
                    let mut chars = word.chars();
                    chars.next().map_or(String::new(), |c| {
                        c.to_uppercase().collect::<String>() + chars.as_str()
                    })
                })
                .collect::<Vec<_>>()
                .join(" ");
        }
    }
    .into()
}
pub fn choices(
    benq: bool,
    name: &str,
    capabilities: Option<&Capabilities>,
    current: Option<u16>,
) -> Vec<Choice> {
    let Ok(feature) = features::feature(benq, name) else {
        return Vec::new();
    };
    let listed = capabilities
        .and_then(|caps| caps.vcp.get(&feature.code))
        .and_then(Option::as_ref);
    let mut result = Vec::new();
    for &(key, value) in feature.values {
        let supported = listed.map_or(!matches!(name, "input" | "kvm"), |values| {
            values.contains(&value)
        });
        if (supported || current == Some(value))
            && !result.iter().any(|choice: &Choice| choice.value == value)
        {
            result.push(Choice {
                name: key.into(),
                label: match (name, key) {
                    ("mute", "on") => "Muted".into(),
                    ("mute", "off") => "Sound on".into(),
                    _ => label(key),
                },
                value,
            });
        }
    }
    if name == "input" {
        for value in listed.into_iter().flatten().copied().chain(current) {
            if !result.iter().any(|choice| choice.value == value) {
                result.push(Choice {
                    name: format!("0x{value:02x}"),
                    label: format!("Input 0x{value:02X}"),
                    value,
                });
            }
        }
    }
    result
}
pub fn value(status: &Status, name: &str) -> Option<u16> {
    status.get(name).and_then(|reading| reading.value)
}
/// Levels that only take effect in another control's mode are disabled outside that mode.
pub fn level_enabled(name: &str, status: &Status) -> bool {
    match name {
        "night-protection-level" => value(status, "night-protection").is_some_and(|v| v != 0),
        "red-gain" | "green-gain" | "blue-gain" => {
            let user = features::COLOR_TEMPERATURES
                .iter()
                .find(|(name, _)| *name == "user")
                .map(|(_, value)| *value);
            user.is_some() && value(status, "color-temperature") == user
        }
        _ => true,
    }
}
/// Levels with small native scales show the monitor's own value instead of a percentage.
pub fn shows_percent(name: &str) -> bool {
    !matches!(
        name,
        "sharpness" | "low-blue-light" | "night-protection-level"
    )
}
/// Picks the bus to target when the user named none. A refresh may move to another
/// connected monitor; a write never does, so it cannot reach a monitor the user did not see.
pub fn auto_bus(previous: Option<u32>, connected: &[u32], refresh: bool) -> Result<Option<u32>> {
    match previous {
        Some(bus) if connected.contains(&bus) => Ok(Some(bus)),
        _ if refresh => Ok(connected.first().copied()),
        Some(bus) => {
            bail!("The monitor on i2c-{bus} is disconnected. Refresh to find connected monitors.")
        }
        None => bail!("No monitor is selected. Refresh to find connected monitors."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use freepilot::FeatureReading;

    fn status(values: &[(&'static str, u16)]) -> Status {
        values
            .iter()
            .map(|&(name, value)| {
                let reading = FeatureReading {
                    code: 0,
                    name: Some(name),
                    kind: None,
                    value: Some(value),
                    max: None,
                    label: None,
                };
                (name, reading)
            })
            .collect()
    }
    #[test]
    fn night_level_needs_night_protection_on() {
        let level = "night-protection-level";
        assert!(!level_enabled(level, &status(&[("night-protection", 0)])));
        assert!(level_enabled(level, &status(&[("night-protection", 1)])));
        assert!(level_enabled(level, &status(&[("night-protection", 2)])));
        assert!(!level_enabled(level, &Status::new()));
    }
    #[test]
    fn rgb_gains_need_the_user_color_temperature() {
        // 0x0B is the BenQ RD "User" color temperature, 0x05 is 6500 K.
        assert!(level_enabled(
            "red-gain",
            &status(&[("color-temperature", 0x0b)])
        ));
        assert!(!level_enabled(
            "blue-gain",
            &status(&[("color-temperature", 0x05)])
        ));
        assert!(!level_enabled("green-gain", &Status::new()));
        assert!(level_enabled("brightness", &Status::new()));
    }
    #[test]
    fn native_scales_are_not_shown_as_percentages() {
        assert!(shows_percent("brightness"));
        assert!(!shows_percent("sharpness"));
        assert!(!shows_percent("night-protection-level"));
    }
    #[test]
    fn auto_selection_only_moves_to_another_monitor_on_refresh() {
        assert_eq!(auto_bus(Some(7), &[5, 7], false).unwrap(), Some(7));
        assert_eq!(auto_bus(None, &[5, 7], true).unwrap(), Some(5));
        assert_eq!(auto_bus(Some(7), &[5], true).unwrap(), Some(5));
        assert_eq!(auto_bus(Some(7), &[], true).unwrap(), None);
        assert!(auto_bus(Some(7), &[5], false).is_err());
        assert!(auto_bus(None, &[5], false).is_err());
    }
    #[test]
    fn mute_choices_describe_the_sound_state() {
        assert_eq!(
            choices(false, "mute", None, None)
                .iter()
                .map(|c| c.label.as_str())
                .collect::<Vec<_>>(),
            ["Muted", "Sound on"]
        );
        assert_eq!(label("kvm"), "KVM");
    }
    #[test]
    fn rd280ug_choices_use_advertised_values_and_keep_unknown_ports_explicit() {
        let caps =
            freepilot::capabilities::parse("vcp(60(0F 11 13) DC(0A 0F 12 1F 23 30 31 32 3A))");
        let inputs = choices(true, "input", Some(&caps), Some(15));
        assert_eq!(
            inputs.iter().map(|c| c.label.as_str()).collect::<Vec<_>>(),
            ["DisplayPort", "HDMI", "USB-C"]
        );
        assert!(
            !choices(true, "picture-mode", Some(&caps), Some(15))
                .iter()
                .any(|choice| choice.name == "game")
        );
        let caps = freepilot::capabilities::parse("vcp(60(0F 1B))");
        assert_eq!(
            choices(false, "input", Some(&caps), None)
                .last()
                .unwrap()
                .label,
            "Input 0x1B"
        );
    }
    #[test]
    fn kvm_and_color_choices_follow_monitor_capabilities() {
        let caps = freepilot::capabilities::parse(
            "vcp(E4(02 03 04) 72(50 64 78 8C A0) 14(05 08 0B) D1(00 01 02))",
        );
        assert_eq!(
            choices(true, "kvm", Some(&caps), Some(4))
                .iter()
                .map(|c| c.label.as_str())
                .collect::<Vec<_>>(),
            ["USB-B", "USB-C", "Auto"]
        );
        assert_eq!(
            choices(true, "gamma", Some(&caps), Some(120))
                .iter()
                .map(|c| c.name.as_str())
                .collect::<Vec<_>>(),
            ["1.8", "2.0", "2.2", "2.4", "2.6"]
        );
        assert_eq!(
            choices(true, "night-protection", Some(&caps), Some(0))
                .iter()
                .map(|c| (c.label.as_str(), c.value))
                .collect::<Vec<_>>(),
            [("Off", 0), ("On", 1), ("Auto", 2)]
        );
        assert_eq!(
            choices(true, "kvm", None, Some(4))
                .iter()
                .map(|c| c.value)
                .collect::<Vec<_>>(),
            [4]
        );
        assert!(choices(false, "kvm", Some(&caps), None).is_empty());
    }
    #[test]
    fn missing_or_malformed_input_lists_never_invent_ports() {
        for caps in [
            None,
            Some(freepilot::capabilities::parse("vcp(60)")),
            Some(freepilot::capabilities::parse("vcp(60(broken))")),
        ] {
            assert_eq!(
                choices(true, "input", caps.as_ref(), Some(0x13))
                    .iter()
                    .map(|c| c.value)
                    .collect::<Vec<_>>(),
                [0x13]
            );
            assert!(choices(true, "input", caps.as_ref(), None).is_empty());
        }
    }
    #[test]
    fn current_choices_survive_incomplete_capability_lists() {
        let caps = freepilot::capabilities::parse("vcp(60(0F 11))");
        assert!(
            choices(true, "input", Some(&caps), Some(0x13))
                .iter()
                .any(|c| c.value == 0x13)
        );
    }
}
