use freepilot::{
    FeatureReading, capabilities,
    config::{Profile, Step},
    displays::{self, Display},
    features, transport,
};

#[test]
fn reads_continuous_and_full_width_choice_values() {
    let readings = transport::parse_terse(
        "VCP 10 C 40 100\nVCP DC SNC x30\nVCP E4 CNC x00 x00 x12 x34\nVCP 62 ERR\n",
    )
    .unwrap();
    assert_eq!(readings[0].value, Some(40));
    assert_eq!(readings[0].max, Some(100));
    assert_eq!(readings[1].value, Some(0x30));
    assert_eq!(readings[2].value, Some(0x1234));
    assert_eq!(readings[3].value, None);
    assert!(transport::parse_terse("VCP 10 C garbage 100").is_err());
    assert!(transport::parse_terse("VCP E4 CNC x00 x00 x100 x00").is_err());
}
#[test]
fn a_failed_getvcp_is_usable_while_any_requested_code_was_read() {
    let codes = [0x10, 0x62, 0x8d];
    let output = |succeeded, stdout: &str| transport::CommandOutput {
        succeeded,
        stdout: stdout.into(),
        stderr: "Display not found".into(),
    };
    let values = |readings: Vec<transport::Reading>| {
        readings
            .iter()
            .map(|reading| (reading.code, reading.value))
            .collect::<Vec<_>>()
    };
    let succeeded_with_errors = output(true, "VCP 10 C 40 100\nVCP 62 ERR\n");
    assert_eq!(
        values(transport::readings_from(&codes, &succeeded_with_errors).unwrap()),
        [(0x10, Some(40)), (0x62, None)]
    );
    // ddcutil prints no VCP line for an unreadable feature and exits non-zero.
    let failed_with_partial_readings = output(
        false,
        "VCP 10 C 40 100\nVCP 62 ERR\nFeature 8d (Audio mute) is not readable\n",
    );
    assert_eq!(
        values(transport::readings_from(&codes, &failed_with_partial_readings).unwrap()),
        [(0x10, Some(40)), (0x62, None)]
    );
    let failed_without_readings = output(false, "");
    let error = transport::readings_from(&codes, &failed_without_readings).unwrap_err();
    assert!(error.to_string().contains("Display not found"), "{error}");
    let failed_with_only_other_codes = output(false, "VCP 12 C 50 100\n");
    assert!(transport::readings_from(&codes, &failed_with_only_other_codes).is_err());
}
#[test]
fn feature_readings_keep_the_status_json_shape() {
    let known = FeatureReading::new(
        true,
        0xdc,
        Some(&transport::Reading {
            code: 0xdc,
            value: Some(0x30),
            max: None,
        }),
    );
    assert_eq!(
        serde_json::to_string(&known).unwrap(),
        r#"{"code":220,"name":"picture-mode","kind":"choice","value":48,"max":null,"label":"coding-dark"}"#
    );
    let unknown = FeatureReading::new(false, 0xdc, None);
    assert_eq!(
        serde_json::to_string(&unknown).unwrap(),
        r#"{"code":220,"name":null,"kind":"unknown","value":null,"max":null,"label":null}"#
    );
}
#[test]
fn strict_writes_refuse_values_above_the_reported_maximum() {
    let step = |code, value, label: &str| Step {
        code,
        value,
        label: label.into(),
    };
    let reading = |code, max| transport::Reading {
        code,
        value: Some(5),
        max,
    };
    let readings = [reading(0x87, Some(10)), reading(0x10, None)];
    assert!(freepilot::check_reported_maxima(&[step(0x87, 10, "sharpness 10")], &readings).is_ok());
    let error =
        freepilot::check_reported_maxima(&[step(0x87, 50, "sharpness 50")], &readings).unwrap_err();
    assert_eq!(
        error.to_string(),
        "sharpness 50 exceeds the monitor's maximum 10"
    );
    // Without a reported maximum there is nothing to check against.
    assert!(
        freepilot::check_reported_maxima(&[step(0x10, 90, "brightness 90")], &readings).is_ok()
    );
    assert!(freepilot::check_reported_maxima(&[step(0x12, 90, "contrast 90")], &readings).is_ok());
}
#[test]
fn capability_codes_serialize_as_hex_in_code_order() {
    let caps = capabilities::parse("vcp(87 10 60(0F 11) DC)");
    let json = serde_json::to_value(&caps).unwrap();
    let keys: Vec<_> = json["vcp"].as_object().unwrap().keys().cloned().collect();
    assert_eq!(keys, ["0x10", "0x60", "0x87", "0xdc"]);
    assert_eq!(json["vcp"]["0x60"], serde_json::json!([15, 17]));
}
#[test]
fn capabilities_enforce_choices_but_not_continuous_value_lists() {
    let caps = capabilities::parse("(prot(monitor)model(RD280U)vcp(1012 60(0F1113) DC(30 31)))");
    assert!(caps.check(0x60, 0x13, true).is_ok());
    assert!(caps.check(0x60, 0x14, true).is_err());
    assert!(caps.check(0x62, 40, false).is_err());
    assert!(caps.check(0x10, 40, false).is_ok());
    let malformed = capabilities::parse("vcp(60(garbage))");
    assert!(malformed.check(0x60, 0x13, true).is_ok());
    for text in ["", "💡vcp(60(13))", "vcp(60(13", "vcp(💡)"] {
        let _ = capabilities::parse(text);
    }
}
#[test]
fn profiles_validate_every_setting_and_put_input_last() {
    let profile: Profile = toml::from_str(
        "input = 'usb-c'\nbrightness = 40\npicture-mode = 'coding-dark'\n[vcp]\n'0xd1' = 2\n",
    )
    .unwrap();
    let steps = profile.plan(true).unwrap();
    assert_eq!(
        steps.iter().map(|s| (s.code, s.value)).collect::<Vec<_>>(),
        [(0xdc, 0x30), (0x10, 40), (0xd1, 2), (0x60, 0x13)]
    );
    assert!(profile.plan(false).is_err());
    for text in [
        "brightness = 101",
        "brightness = true",
        "unknown = 1",
        "[vcp]\n'0xe4' = 1",
        "brightness = 40\n[vcp]\n'0x10' = 50",
        "[vcp]\n'16' = 1\n'0x10' = 2",
    ] {
        assert!(
            toml::from_str::<Profile>(text).unwrap().plan(true).is_err(),
            "{text}"
        );
    }
}
#[test]
fn benq_values_are_never_used_for_other_monitors() {
    assert_eq!(
        features::setting(true, "input", "usb-c").unwrap(),
        (0x60, 0x13)
    );
    assert!(features::setting(false, "input", "usb-c").is_err());
    assert!(features::setting(false, "picture-mode", "coding-dark").is_err());
    assert!(features::code(false, "256").is_err());
    assert_eq!(features::number("0x1A").unwrap(), 26);
    assert_eq!(
        features::number("2.2").unwrap_err().to_string(),
        r#""2.2" is not a number"#
    );
}
#[test]
fn serial_selection_precedes_model_and_ambiguity_is_an_error() {
    let displays = vec![
        Display {
            connector: "card1-DP-1".into(),
            serial: "desk".into(),
            ..Default::default()
        },
        Display {
            connector: "card1-DP-2".into(),
            model: "desk".into(),
            ..Default::default()
        },
    ];
    let aliases = Default::default();
    assert_eq!(
        displays::select(&displays, "desk", &aliases)
            .unwrap()
            .connector,
        "card1-DP-1"
    );
    let duplicates = vec![
        Display {
            model: "RD280U".into(),
            ..Default::default()
        };
        2
    ];
    assert!(displays::select(&duplicates, "RD", &aliases).is_err());
}
#[test]
fn edid_rejects_corruption_before_using_identity() {
    assert!(displays::parse_edid(&[0; 127]).is_err());
    let mut bytes = [0u8; 128];
    bytes[..8].copy_from_slice(&[0, 255, 255, 255, 255, 255, 255, 0]);
    bytes[8..10].copy_from_slice(&0x09d1u16.to_be_bytes());
    bytes[54..59].copy_from_slice(&[0, 0, 0, 0xfc, 0]);
    bytes[59..65].copy_from_slice(b"RD280U");
    bytes[127] = 0u8.wrapping_sub(bytes[..127].iter().fold(0u8, |sum, b| sum.wrapping_add(*b)));
    let display = displays::parse_edid(&bytes).unwrap();
    assert_eq!(display.manufacturer, "BNQ");
    assert!(display.benq());
    bytes[60] ^= 1;
    assert!(displays::parse_edid(&bytes).is_err());
}

#[test]
fn missing_sysfs_is_an_empty_display_list() {
    let directory = tempfile::tempdir().unwrap();
    assert!(
        displays::discover(&directory.path().join("missing-drm"))
            .unwrap()
            .is_empty()
    );
}

#[test]
fn displayport_uses_aux_child_while_hdmi_uses_the_ddc_link() {
    use std::{fs, os::unix::fs::symlink};
    let root = tempfile::tempdir().unwrap();
    let linked_bus = root.path().join("i2c-0");
    fs::create_dir(&linked_bus).unwrap();
    for name in ["card1-DP-1", "card1-eDP-1", "card1-HDMI-A-1"] {
        let connector = root.path().join(name);
        fs::create_dir(&connector).unwrap();
        fs::write(connector.join("status"), "connected\n").unwrap();
        symlink(&linked_bus, connector.join("ddc")).unwrap();
        fs::create_dir(connector.join("i2c-9")).unwrap();
    }
    let found = displays::discover(root.path()).unwrap();
    assert_eq!(
        found
            .iter()
            .find(|d| d.connector == "card1-DP-1")
            .unwrap()
            .bus,
        Some(9)
    );
    assert_eq!(
        found
            .iter()
            .find(|d| d.connector == "card1-eDP-1")
            .unwrap()
            .bus,
        Some(9)
    );
    assert_eq!(
        found
            .iter()
            .find(|d| d.connector == "card1-HDMI-A-1")
            .unwrap()
            .bus,
        Some(0)
    );
    fs::remove_dir(root.path().join("card1-DP-1/i2c-9")).unwrap();
    assert_eq!(
        displays::discover(root.path())
            .unwrap()
            .iter()
            .find(|d| d.connector == "card1-DP-1")
            .unwrap()
            .bus,
        Some(0)
    );
}

#[test]
fn extended_benq_controls_use_verified_wire_values_and_native_limits() {
    for (name, text, code, value) in [
        ("night-protection", "off", 0xd1, 0),
        ("night-protection", "auto", 0xd1, 2),
        ("color-temperature", "user", 0x14, 11),
        ("color-temperature", "6500k", 0x14, 5),
        ("gamma", "2.2", 0x72, 120),
        ("bright-intelligence", "bi-plus", 0x81, 1),
        ("kvm", "usb-c", 0xe4, 3),
        ("low-blue-light", "5", 0x19, 5),
        ("night-protection-level", "1", 0xd0, 1),
        ("red-gain", "100", 0x16, 100),
        // Raw features have no known range, so their values are not bounds-checked.
        ("gamut", "300", 0x5f, 300),
    ] {
        assert_eq!(features::setting(true, name, text).unwrap(), (code, value));
        assert!(features::setting(false, name, text).is_err());
    }
    for (name, value) in [
        ("low-blue-light", "6"),
        ("night-protection-level", "0"),
        ("night-protection-level", "11"),
        ("blue-gain", "101"),
    ] {
        assert!(features::setting(true, name, value).is_err());
    }
    assert_eq!(features::slider_bounds("sharpness", Some(10)), (0, 10));
    assert_eq!(
        features::slider_bounds("night-protection-level", None),
        (1, 10)
    );
    assert_eq!(features::slider_bounds("low-blue-light", Some(255)), (0, 5));
}
