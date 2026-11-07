use freepilot::{
    Monitor, Selection,
    config::{Alias, Config},
    displays::{self, Display},
};
use std::collections::BTreeMap;

fn display(connector: &str, bus: Option<u32>, serial: &str) -> Display {
    Display {
        connector: connector.into(),
        bus,
        manufacturer: "BNQ".into(),
        model: "BenQ RD280U".into(),
        serial: serial.into(),
        ..Default::default()
    }
}
fn config_with_alias(name: &str, alias: Alias) -> Config {
    Config {
        monitors: BTreeMap::from([(name.to_string(), alias)]),
        ..Default::default()
    }
}
fn monitor_selector(selector: &str) -> Selection {
    Selection {
        monitor: Some(selector.into()),
        ..Default::default()
    }
}

#[test]
fn connect_resolves_bus_and_model_by_documented_precedence() {
    let two_monitors = [
        display("card1-DP-1", Some(4), "desk"),
        display("card1-DP-2", Some(5), "OTHER"),
    ];
    let desk_on_dp2 = config_with_alias(
        "desk",
        Alias {
            connector: Some("DP-2".into()),
            model: Some("mccs".into()),
            ..Default::default()
        },
    );
    let no_config = Config::default();
    struct Case<'a> {
        name: &'a str,
        selection: Selection,
        config: &'a Config,
        displays: &'a [Display],
        bus: Option<u32>,
        benq: bool,
    }
    let cases = [
        Case {
            name: "an alias beats a display whose serial is the alias name",
            selection: monitor_selector("desk"),
            config: &desk_on_dp2,
            displays: &two_monitors,
            bus: Some(5),
            benq: false,
        },
        Case {
            name: "--model beats the alias model",
            selection: Selection {
                model: Some("benq-rd".into()),
                ..monitor_selector("desk")
            },
            config: &desk_on_dp2,
            displays: &two_monitors,
            bus: Some(5),
            benq: true,
        },
        Case {
            name: "without a model, the EDID decides",
            selection: monitor_selector("DP-1"),
            config: &no_config,
            displays: &two_monitors,
            bus: Some(4),
            benq: true,
        },
        Case {
            name: "one monitor with a bus is selected automatically",
            selection: Selection::default(),
            config: &no_config,
            displays: &[
                display("card1-DP-1", Some(4), "A"),
                display("card1-HDMI-A-1", None, "B"),
            ],
            bus: Some(4),
            benq: true,
        },
        Case {
            name: "several buses leave the choice to ddcutil",
            selection: Selection::default(),
            config: &no_config,
            displays: &two_monitors,
            bus: None,
            benq: false,
        },
    ];
    for case in cases {
        let monitor = Monitor::connect(&case.selection, case.config, case.displays)
            .unwrap_or_else(|error| panic!("{}: {error:#}", case.name));
        assert_eq!(monitor.transport.bus, case.bus, "{}", case.name);
        assert_eq!(monitor.benq, case.benq, "{}", case.name);
    }
}
#[test]
fn selected_monitor_without_a_bus_is_an_error() {
    let displays = [display("card1-DP-1", None, "A")];
    assert!(Monitor::connect(&monitor_selector("DP-1"), &Config::default(), &displays).is_err());
}
#[test]
fn alias_connectors_match_short_or_full_names_and_never_fall_through() {
    let displays = [
        display("card1-DP-1", Some(4), "A"),
        display("card1-DP-2", Some(5), "B"),
    ];
    for connector in ["DP-2", "card1-DP-2"] {
        let aliases = config_with_alias(
            "desk",
            Alias {
                connector: Some(connector.into()),
                ..Default::default()
            },
        )
        .monitors;
        let selected = displays::select(&displays, "desk", &aliases).unwrap();
        assert_eq!(selected.connector, "card1-DP-2", "{connector}");
    }
    // "RD280U" would match both displays by model, and "A" would match by serial.
    for name in ["RD280U", "A"] {
        let aliases = config_with_alias(
            name,
            Alias {
                connector: Some("HDMI-A-1".into()),
                ..Default::default()
            },
        )
        .monitors;
        let error = displays::select(&displays, name, &aliases).unwrap_err();
        assert!(
            error.to_string().contains("No connected monitor"),
            "{error}"
        );
    }
}
#[test]
fn empty_selectors_match_nothing() {
    let serial_less = [display("card1-DP-1", Some(4), "")];
    assert!(displays::select(&serial_less, "", &BTreeMap::new()).is_err());
    for alias in ["serial = ''", "connector = ''"] {
        let error = Config::from_toml(&format!("[monitors.desk]\n{alias}\n")).unwrap_err();
        assert!(
            format!("{error:#}").contains("monitor alias \"desk\""),
            "{error:#}"
        );
    }
}
#[test]
fn config_errors_name_the_profile_and_raw_key() {
    let error =
        Config::from_toml("[profiles.night]\n[profiles.night.vcp]\n'0x1ff' = 1\n").unwrap_err();
    let message = format!("{error:#}");
    assert!(message.contains("profile \"night\""), "{message}");
    assert!(message.contains("raw VCP key \"0x1ff\""), "{message}");
    for reset in ["0x04", "0x05", "0x06", "0x08", "0x0a", "0xb0"] {
        let text = format!("[profiles.night.vcp]\n'{reset}' = 1\n");
        assert!(Config::from_toml(&text).is_err(), "{reset}");
    }
    let error = Config::from_toml("[profiles.night]\nbrightness = 101\n").unwrap_err();
    assert!(
        format!("{error:#}").contains("profile \"night\""),
        "{error:#}"
    );
}
