use async_channel::Sender;
use ksni::{
    MenuItem, Tray,
    menu::{CheckmarkItem, StandardItem, SubMenu},
};

#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    Open,
    Quit,
    Mode { name: String, revision: u64 },
}

#[derive(Clone, Default)]
pub struct State {
    pub revision: u64,
    pub benq: bool,
    pub modes: Vec<(String, String)>,
    pub busy: bool,
    pub current_mode: Option<String>,
    pub monitor: String,
    pub message: String,
}

pub struct FreepilotTray {
    pub events: Sender<Event>,
    pub state: State,
}
impl FreepilotTray {
    pub fn update_state(&mut self, state: State) {
        // Background publications can arrive out of order after a fast monitor operation.
        if state.revision > self.state.revision {
            self.state = state;
        }
    }
    fn send(&self, event: Event) {
        let _ = self.events.try_send(event);
    }
}
impl Tray for FreepilotTray {
    fn id(&self) -> String {
        "freepilot".into()
    }
    fn title(&self) -> String {
        "Freepilot".into()
    }
    fn icon_name(&self) -> String {
        "video-display".into()
    }
    fn icon_pixmap(&self) -> Vec<ksni::Icon> {
        // StatusNotifier pixmaps use network-order ARGB, with transparent padding.
        let mut data = vec![0; 24 * 24 * 4];
        for y in 3..22 {
            for x in 2..22 {
                let screen = (3..17).contains(&y);
                let stand = (10..14).contains(&x) && (17..20).contains(&y);
                let base = (6..18).contains(&x) && (20..22).contains(&y);
                if screen || stand || base {
                    let pixel = if screen && (4..20).contains(&x) && (5..15).contains(&y) {
                        [255, 120, 120, 120]
                    } else {
                        [255, 225, 225, 225]
                    };
                    let offset = (y * 24 + x) * 4;
                    data[offset..offset + 4].copy_from_slice(&pixel);
                }
            }
        }
        vec![ksni::Icon {
            width: 24,
            height: 24,
            data,
        }]
    }
    fn tool_tip(&self) -> ksni::ToolTip {
        ksni::ToolTip {
            title: "Freepilot".into(),
            description: format!("{}\n{}", self.state.monitor, self.state.message),
            ..Default::default()
        }
    }
    fn activate(&mut self, _: i32, _: i32) {
        self.send(Event::Open);
    }
    fn menu(&self) -> Vec<MenuItem<Self>> {
        vec![
            StandardItem {
                label: "Open Freepilot".into(),
                icon_name: "video-display".into(),
                activate: Box::new(|tray: &mut Self| tray.send(Event::Open)),
                ..Default::default()
            }
            .into(),
            StandardItem {
                label: self.state.monitor.clone(),
                enabled: false,
                ..Default::default()
            }
            .into(),
            SubMenu {
                label: "Picture mode".into(),
                enabled: self.state.benq && !self.state.busy,
                submenu: self
                    .state
                    .modes
                    .iter()
                    .map(|(name, label)| {
                        let name = name.clone();
                        let revision = self.state.revision;
                        CheckmarkItem {
                            label: label.clone(),
                            checked: self.state.current_mode.as_deref() == Some(name.as_str()),
                            enabled: self.state.benq && !self.state.busy,
                            activate: Box::new(move |tray: &mut Self| {
                                if tray.state.benq
                                    && !tray.state.busy
                                    && tray.state.revision == revision
                                {
                                    tray.send(Event::Mode {
                                        name: name.clone(),
                                        revision,
                                    });
                                }
                            }),
                            ..Default::default()
                        }
                        .into()
                    })
                    .collect(),
                ..Default::default()
            }
            .into(),
            MenuItem::Separator,
            StandardItem {
                label: "Quit".into(),
                icon_name: "application-exit".into(),
                activate: Box::new(|tray: &mut Self| tray.send(Event::Quit)),
                ..Default::default()
            }
            .into(),
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tray_activation_and_menu_actions_reach_the_app() {
        let (events, receiver) = async_channel::unbounded();
        let mut tray = FreepilotTray {
            events,
            state: State::default(),
        };
        tray.activate(0, 0);
        assert_eq!(receiver.try_recv().unwrap(), Event::Open);
        for (label, expected) in [("Open Freepilot", Event::Open), ("Quit", Event::Quit)] {
            let item = tray
                .menu()
                .into_iter()
                .find_map(|item| match item {
                    MenuItem::Standard(item) if item.label == label => Some(item),
                    _ => None,
                })
                .unwrap();
            (item.activate)(&mut tray);
            assert_eq!(receiver.try_recv().unwrap(), expected);
        }
    }
    fn mode_item(tray: &FreepilotTray, name: &str) -> CheckmarkItem<FreepilotTray> {
        tray.menu()
            .into_iter()
            .find_map(|item| match item {
                MenuItem::SubMenu(menu) if menu.label == "Picture mode" => Some(menu),
                _ => None,
            })
            .unwrap()
            .submenu
            .into_iter()
            .find_map(|item| match item {
                MenuItem::Checkmark(item) if item.label == crate::ui_model::label(name) => {
                    Some(item)
                }
                _ => None,
            })
            .unwrap()
    }
    #[test]
    fn mode_menu_marks_current_mode_and_sends_the_requested_mode() {
        let (events, receiver) = async_channel::unbounded();
        let mut tray = FreepilotTray {
            events,
            state: State {
                revision: 1,
                benq: true,
                modes: crate::ui_model::choices(true, "picture-mode", None, None)
                    .into_iter()
                    .map(|choice| (choice.name, choice.label))
                    .collect(),
                current_mode: Some("coding-dark".into()),
                ..Default::default()
            },
        };
        assert!(mode_item(&tray, "coding-dark").checked);
        let item = mode_item(&tray, "coding-light");
        assert!(!item.checked);
        assert!(item.enabled);
        (item.activate)(&mut tray);
        assert_eq!(
            receiver.try_recv().unwrap(),
            Event::Mode {
                name: "coding-light".into(),
                revision: 1
            }
        );
    }
    #[test]
    fn busy_unsupported_and_stale_mode_menus_never_send_writes() {
        let (events, receiver) = async_channel::unbounded();
        let mut tray = FreepilotTray {
            events,
            state: State {
                revision: 1,
                benq: true,
                modes: crate::ui_model::choices(true, "picture-mode", None, None)
                    .into_iter()
                    .map(|choice| (choice.name, choice.label))
                    .collect(),
                ..Default::default()
            },
        };
        let stale = mode_item(&tray, "coding-dark");
        tray.state.busy = true;
        assert!(!mode_item(&tray, "coding-dark").enabled);
        (stale.activate)(&mut tray);
        tray.state.busy = false;
        tray.state.revision = 2;
        (stale.activate)(&mut tray);
        tray.state.benq = false;
        let unsupported = mode_item(&tray, "coding-dark");
        assert!(!unsupported.enabled);
        (unsupported.activate)(&mut tray);
        assert!(receiver.try_recv().is_err());
    }
    #[test]
    fn later_publication_cannot_be_overwritten_by_an_older_monitor_state() {
        let (events, _) = async_channel::unbounded();
        let mut tray = FreepilotTray {
            events,
            state: State::default(),
        };
        tray.update_state(State {
            revision: 2,
            busy: false,
            ..Default::default()
        });
        tray.update_state(State {
            revision: 1,
            busy: true,
            ..Default::default()
        });
        assert!(!tray.state.busy);
    }
}
