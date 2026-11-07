use crate::{
    slider::{Changed, Slider},
    theme::{self, ACCENT, BACKGROUND, BORDER, MUTED, PANEL},
    ui_model::{self, Choice},
};
use anyhow::Result;
use freepilot::capabilities::Capabilities;
use freepilot::{
    Monitor, Selection, Status,
    config::{Config, Step},
    displays::{self, Display},
    features,
};
use gpui::{prelude::*, *};
use std::{collections::BTreeMap, path::Path};

/// Narrower windows stack the two control columns.
const TWO_COLUMN_MIN_WIDTH: f32 = 900.;

#[derive(Clone)]
enum Operation {
    Refresh,
    Write {
        feature: &'static str,
        value: String,
    },
    Profile(String),
    Switch {
        feature: &'static str,
        value: u16,
    },
}
/// Everything a background operation needs; the view owns the originals.
struct Request {
    selection: Selection,
    auto_bus: Option<u32>,
    operation: Operation,
    capabilities: Option<Capabilities>,
    last_config: Config,
}
struct Outcome {
    displays: Vec<Display>,
    auto_bus: Option<u32>,
    result: Result<Snapshot>,
}
struct Snapshot {
    capabilities: Option<Capabilities>,
    config: Config,
    monitor: Option<Monitor>,
    /// `Err` describes a successful write whose read-back failed.
    status: std::result::Result<Status, String>,
    warning: Option<String>,
}
struct Freepilot {
    /// The target the user chose on the command line or in the picker; never moved.
    selection: Selection,
    /// The bus picked automatically when `selection` names no target.
    auto_bus: Option<u32>,
    displays: Vec<Display>,
    config: Config,
    monitor: Option<Monitor>,
    status: Status,
    message: String,
    busy: bool,
    pending_switch: Option<(&'static str, Choice)>,
    capabilities: Option<Capabilities>,
    sliders: BTreeMap<&'static str, Entity<Slider>>,
    error: bool,
    monitor_picker_open: bool,
    advanced_open: bool,
    focus: FocusHandle,
    tray: Option<std::sync::Arc<ksni::blocking::Handle<crate::tray::FreepilotTray>>>,
    tray_revision: u64,
}
impl Freepilot {
    fn new(selection: Selection, cx: &mut Context<Self>) -> Self {
        let mut sliders = BTreeMap::new();
        for &(name, label) in features::GUI_LEVELS {
            let slider = cx.new(|cx| Slider::new(label, ui_model::shows_percent(name), cx));
            cx.subscribe(&slider, move |view, _, event: &Changed, cx| {
                view.perform(
                    Operation::Write {
                        feature: name,
                        value: event.0.to_string(),
                    },
                    cx,
                )
            })
            .detach();
            sliders.insert(name, slider);
        }
        let mut view = Self {
            selection,
            auto_bus: None,
            displays: Vec::new(),
            config: Config::default(),
            monitor: None,
            status: Status::new(),
            message: "Discovering monitors…".into(),
            busy: false,
            pending_switch: None,
            capabilities: None,
            sliders,
            error: false,
            monitor_picker_open: false,
            advanced_open: false,
            focus: cx.focus_handle(),
            tray: None,
            tray_revision: 0,
        };
        view.perform(Operation::Refresh, cx);
        view
    }
    fn perform(&mut self, operation: Operation, cx: &mut Context<Self>) {
        if self.busy {
            return;
        }
        self.busy = true;
        self.error = false;
        self.message = match &operation {
            Operation::Refresh => "Refreshing monitor…".into(),
            Operation::Write { feature, .. } => {
                format!("Updating {}…", ui_model::label(feature).to_lowercase())
            }
            Operation::Profile(name) => format!("Applying {name}…"),
            Operation::Switch { feature, .. } => {
                format!("Switching {}…", ui_model::label(feature).to_lowercase())
            }
        };
        self.synchronize_sliders(cx);
        self.update_tray(cx);
        let request = Request {
            selection: self.selection.clone(),
            auto_bus: self.auto_bus,
            operation,
            capabilities: self.capabilities.clone(),
            last_config: self.config.clone(),
        };
        let task = cx
            .background_executor()
            .spawn(async move { run_operation(request) });
        cx.spawn(async move |entity, cx| {
            let outcome = task.await;
            let _ = entity.update(cx, |view, cx| {
                view.finish_operation(outcome);
                view.synchronize_sliders(cx);
                view.update_tray(cx);
                cx.notify();
            });
        })
        .detach();
        cx.notify();
    }
    fn finish_operation(&mut self, outcome: Outcome) {
        self.busy = false;
        self.displays = outcome.displays;
        self.auto_bus = outcome.auto_bus;
        self.pending_switch = None;
        let snapshot = match outcome.result {
            Ok(snapshot) => snapshot,
            Err(error) => {
                self.error = true;
                self.message = format!("{error:#}");
                return;
            }
        };
        self.capabilities = snapshot.capabilities;
        self.config = snapshot.config;
        self.monitor = snapshot.monitor;
        let warning = snapshot.warning;
        match snapshot.status {
            Ok(status) => {
                self.status = status;
                self.error = warning.is_some();
                self.message = warning.unwrap_or_else(|| {
                    if self.monitor.is_some() {
                        "Ready"
                    } else {
                        "No monitor with a DDC bus. Connect a monitor and refresh."
                    }
                    .into()
                });
            }
            Err(message) => {
                self.error = true;
                self.message = message;
            }
        }
    }
    fn synchronize_sliders(&self, cx: &mut Context<Self>) {
        for (name, slider) in &self.sliders {
            let reading = self.status.get(name);
            slider.update(cx, |slider, cx| {
                if self.busy {
                    slider.begin_update(cx);
                    return;
                }
                slider.synchronize(
                    reading.and_then(|reading| reading.value),
                    features::slider_bounds(name, reading.and_then(|reading| reading.max)),
                    ui_model::level_enabled(name, &self.status),
                    cx,
                );
            });
        }
    }
    fn value(&self, name: &str) -> Option<u16> {
        ui_model::value(&self.status, name)
    }
    fn has_control(&self, name: &str) -> bool {
        self.status.contains_key(name)
    }
    /// A focusable control whose click (GPUI also clicks a focused element on Enter or Space)
    /// runs `action` only when available and idle, checking live state on activation.
    fn activatable(
        &self,
        id: impl Into<SharedString>,
        label: String,
        selected: bool,
        is_available: impl Fn(&Self) -> bool + 'static,
        action: impl Fn(&mut Self, &mut Context<Self>) + 'static,
        cx: &mut Context<Self>,
    ) -> Stateful<Div> {
        control(id, label, selected, is_available(self))
            .when(self.busy, |control| {
                control.tab_stop(false).cursor_default()
            })
            .on_click(cx.listener(move |view, _, _, cx| {
                if !view.busy && is_available(view) {
                    action(view, cx);
                }
            }))
    }
    fn button(
        &self,
        id: impl Into<SharedString>,
        label: String,
        operation: Operation,
        cx: &mut Context<Self>,
    ) -> Stateful<Div> {
        self.activatable(
            id,
            label,
            false,
            |_| true,
            move |view, cx| view.perform(operation.clone(), cx),
            cx,
        )
    }
    fn choice_group(&self, name: &'static str, cx: &mut Context<Self>) -> Div {
        let current = self.value(name);
        let mut choices = div().flex().flex_wrap().gap_2();
        for choice in self.available_choices(name) {
            let value = choice.name;
            choices = choices.child(self.activatable(
                format!("{name}-{}", choice.value),
                choice.label,
                current == Some(choice.value),
                move |view| view.value(name).is_some(),
                move |view, cx| {
                    view.perform(
                        Operation::Write {
                            feature: name,
                            value: value.clone(),
                        },
                        cx,
                    )
                },
                cx,
            ));
        }
        let heading = match name {
            "night-protection" => "Night protection".to_string(),
            _ => ui_model::label(name),
        };
        div()
            .flex()
            .flex_col()
            .gap_2()
            .child(div().text_sm().text_color(rgb(MUTED)).child(heading))
            .child(choices)
            .when(current.is_none(), |e| {
                e.child(
                    div()
                        .text_xs()
                        .text_color(rgb(MUTED))
                        .child("Unavailable. Refresh or try another picture mode."),
                )
            })
    }
    fn switch_card(&self, name: &'static str, title: &str, cx: &mut Context<Self>) -> Div {
        let mut choices = div().flex().flex_wrap().gap_2();
        let current = self.value(name);
        for choice in self.available_choices(name) {
            let target = choice.value;
            choices = choices.child(self.activatable(
                format!("{name}-{target}"),
                choice.label.clone(),
                current == Some(target),
                move |view| view.value(name).is_some_and(|value| value != target),
                move |view, cx| {
                    view.pending_switch = Some((name, choice.clone()));
                    cx.notify();
                },
                cx,
            ));
        }
        let mut result = card(
            title,
            if name == "kvm" {
                "Route the monitor's USB devices."
            } else {
                ""
            },
        )
        .child(choices);
        let benq = self.monitor.as_ref().is_some_and(|monitor| monitor.benq);
        let listed = features::feature(benq, name).is_ok_and(|feature| {
            self.capabilities
                .as_ref()
                .and_then(|caps| caps.vcp.get(&feature.code))
                .is_some_and(Option::is_some)
        });
        if !listed {
            result = result.child(
                div()
                    .text_xs()
                    .text_color(rgb(MUTED))
                    .child("Choices are unavailable. Refresh to retry detection."),
            );
        }
        if let Some((_, choice)) = self
            .pending_switch
            .clone()
            .filter(|(pending_name, _)| *pending_name == name)
        {
            result = result.child(self.switch_confirmation(name, choice, cx));
        }
        result
    }
    fn switch_confirmation(
        &self,
        name: &'static str,
        choice: Choice,
        cx: &mut Context<Self>,
    ) -> Div {
        let consequence = if name == "kvm" {
            "Your keyboard and mouse may disconnect from this computer."
        } else {
            "The display may stop showing this computer."
        };
        div()
            .p_3()
            .rounded_md()
            .bg(rgb(theme::CONFIRMATION_PANEL))
            .border_1()
            .border_color(rgb(theme::CONFIRMATION_BORDER))
            .flex()
            .flex_col()
            .gap_3()
            .child(
                div()
                    .text_sm()
                    .child(format!("Switch to {}? {consequence}", choice.label)),
            )
            .child(
                div()
                    .flex()
                    .gap_2()
                    .child(self.button(
                        format!("confirm-{name}"),
                        "Switch".into(),
                        Operation::Switch {
                            feature: name,
                            value: choice.value,
                        },
                        cx,
                    ))
                    .child(self.activatable(
                        format!("cancel-{name}"),
                        "Cancel".into(),
                        false,
                        |_| true,
                        |view, cx| {
                            view.pending_switch = None;
                            cx.notify();
                        },
                        cx,
                    )),
            )
    }
    fn available_choices(&self, name: &str) -> Vec<Choice> {
        ui_model::choices(
            self.monitor.as_ref().is_some_and(|m| m.benq),
            name,
            self.capabilities.as_ref(),
            self.value(name),
        )
    }
    fn update_tray(&mut self, cx: &mut Context<Self>) {
        let Some(handle) = self.tray.clone() else {
            return;
        };
        self.tray_revision += 1;
        let monitor = self.monitor.as_ref();
        let label = monitor.map_or_else(
            || "No monitor selected".into(),
            |monitor| {
                self.displays
                    .iter()
                    .find(|display| display.bus.is_some() && display.bus == monitor.transport.bus)
                    .map(|display| format!("{} · {}", display.model, display.short_connector()))
                    .unwrap_or_else(|| {
                        format!(
                            "Monitor on {}",
                            monitor.transport.bus.map_or_else(
                                || format!("display {}", monitor.transport.display.unwrap_or(1)),
                                |bus| format!("i2c-{bus}")
                            )
                        )
                    })
            },
        );
        let state = crate::tray::State {
            revision: self.tray_revision,
            modes: self
                .available_choices("picture-mode")
                .into_iter()
                .map(|choice| (choice.name, choice.label))
                .collect(),
            benq: monitor.is_some_and(|monitor| monitor.benq),
            busy: self.busy,
            current_mode: self
                .status
                .get("picture-mode")
                .and_then(|reading| reading.label)
                .map(str::to_string),
            monitor: label,
            message: self.message.clone(),
        };
        cx.background_executor()
            .spawn(async move {
                handle.update(|tray| tray.update_state(state));
            })
            .detach();
    }
    fn status_badge(&self) -> Div {
        let (text, background, color) = if self.monitor.is_some() {
            (
                "Connected",
                theme::CONNECTED_BADGE,
                theme::CONNECTED_BADGE_TEXT,
            )
        } else {
            ("No display", theme::BADGE, MUTED)
        };
        div()
            .px_3()
            .py_1()
            .rounded_full()
            .text_xs()
            .bg(rgb(background))
            .text_color(rgb(color))
            .child(text)
    }
    fn error_toast(&self, cx: &mut Context<Self>) -> Div {
        div()
            .absolute()
            .bottom_6()
            .right_6()
            .w(px(520.))
            .max_w_full()
            .p_4()
            .rounded_lg()
            .shadow_lg()
            .border_1()
            .border_color(rgb(theme::ERROR_BORDER))
            .bg(rgb(theme::ERROR_PANEL))
            .text_color(rgb(theme::ERROR_TEXT))
            .flex()
            .flex_col()
            .gap_2()
            .occlude()
            .child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap_3()
                    .child(
                        div()
                            .text_sm()
                            .font_weight(FontWeight::SEMIBOLD)
                            .child("Could not complete the update"),
                    )
                    .child(self.activatable(
                        "dismiss-error",
                        "Dismiss".into(),
                        false,
                        |_| true,
                        |view, cx| {
                            view.error = false;
                            cx.notify();
                        },
                        cx,
                    )),
            )
            .child(
                div()
                    .id("error-message")
                    .max_h(px(160.))
                    .overflow_y_scroll()
                    .text_sm()
                    .child(self.message.clone()),
            )
    }
    fn monitor_picker(&self, cx: &mut Context<Self>) -> Div {
        let mut list = card("Choose a display", "");
        for display in &self.displays {
            let bus = display.bus;
            let selected = self
                .monitor
                .as_ref()
                .is_some_and(|m| bus.is_some() && m.transport.bus == bus);
            let model = if display.model.is_empty() {
                "Unknown display"
            } else {
                &display.model
            };
            list = list.child(self.activatable(
                format!("display-{}", display.connector),
                format!("{model} · {}", display.short_connector()),
                selected,
                move |_| bus.is_some(),
                move |view, cx| view.choose_display(bus, cx),
                cx,
            ));
        }
        list
    }
    /// Makes the picked display the explicit target, replacing any command-line target.
    fn choose_display(&mut self, bus: Option<u32>, cx: &mut Context<Self>) {
        self.selection.bus = bus;
        self.selection.display = None;
        self.selection.monitor = None;
        self.selection.model = None;
        self.auto_bus = None;
        self.monitor = None;
        self.status.clear();
        self.capabilities = None;
        self.pending_switch = None;
        self.monitor_picker_open = false;
        self.perform(Operation::Refresh, cx);
    }
    fn header(&self, cx: &mut Context<Self>) -> Div {
        let title = self
            .monitor
            .as_ref()
            .and_then(|m| {
                self.displays
                    .iter()
                    .find(|d| d.bus.is_some() && d.bus == m.transport.bus)
            })
            .map(|d| d.model.as_str())
            .filter(|m| !m.is_empty())
            .unwrap_or("Monitor controls");
        let mut identity = div()
            .flex()
            .flex_col()
            .gap_1()
            .child(div().text_xs().text_color(rgb(MUTED)).child("Freepilot"));
        if self.displays.len() > 1 {
            identity = identity.child(self.activatable(
                "monitor-picker",
                format!("{title} ▾"),
                self.monitor_picker_open,
                |_| true,
                |view, cx| {
                    view.monitor_picker_open = !view.monitor_picker_open;
                    cx.notify();
                },
                cx,
            ));
        } else {
            identity = identity.child(
                div()
                    .text_2xl()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(title.to_string()),
            );
        }
        div()
            .flex()
            .items_center()
            .justify_between()
            .gap_4()
            .child(identity)
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap_3()
                    .child(self.status_badge())
                    .child(self.button("refresh", "Refresh".into(), Operation::Refresh, cx)),
            )
    }
    fn levels_card(&self) -> Div {
        let mut levels = card("Display", "");
        for name in ["brightness", "contrast", "sharpness"] {
            if self.has_control(name) {
                levels = levels.child(self.sliders[name].clone());
            }
        }
        levels
    }
    fn picture_mode_card(&self, cx: &mut Context<Self>) -> Option<Div> {
        let modes = self.available_choices("picture-mode");
        if modes.is_empty() {
            return None;
        }
        let current = self.value("picture-mode");
        let mut grid = div().grid().grid_cols(3).gap_2();
        for choice in modes {
            let value = choice.name;
            grid = grid.child(self.activatable(
                format!("mode-{}", choice.value),
                choice.label,
                current == Some(choice.value),
                |_| true,
                move |view, cx| {
                    view.perform(
                        Operation::Write {
                            feature: "picture-mode",
                            value: value.clone(),
                        },
                        cx,
                    )
                },
                cx,
            ));
        }
        Some(card("Picture mode", "").child(grid))
    }
    fn audio_card(&self, cx: &mut Context<Self>) -> Div {
        let muted = self.value("mute") == Some(1);
        card("Audio", "").child(
            div()
                .flex()
                .items_center()
                .gap_2()
                .child(
                    div()
                        .flex_1()
                        .min_w_0()
                        .child(self.sliders["volume"].clone()),
                )
                .child(self.activatable(
                    "mute",
                    if muted { "Unmute" } else { "Mute" }.into(),
                    muted,
                    |view| view.value("mute").is_some(),
                    |view, cx| {
                        let muted = view.value("mute") == Some(1);
                        view.perform(
                            Operation::Write {
                                feature: "mute",
                                value: if muted { "off" } else { "on" }.into(),
                            },
                            cx,
                        )
                    },
                    cx,
                )),
        )
    }
    fn comfort_card(&self, cx: &mut Context<Self>) -> Option<Div> {
        let names = [
            "low-blue-light",
            "night-protection",
            "night-protection-level",
            "bright-intelligence",
        ];
        self.control_card(card("Eye comfort", ""), &names, cx)
    }
    fn advanced_color_card(&self, cx: &mut Context<Self>) -> Option<Div> {
        let names = [
            "color-temperature",
            "gamma",
            "red-gain",
            "green-gain",
            "blue-gain",
        ];
        if !names.iter().any(|name| self.has_control(name)) {
            return None;
        }
        let toggle = self.activatable(
            "toggle-advanced",
            if self.advanced_open {
                "Hide controls ▴"
            } else {
                "Show controls ▾"
            }
            .into(),
            self.advanced_open,
            |_| true,
            |view, cx| {
                view.advanced_open = !view.advanced_open;
                cx.notify();
            },
            cx,
        );
        let advanced =
            card("Advanced color", "Some picture modes lock color settings.").child(toggle);
        if !self.advanced_open {
            return Some(advanced);
        }
        let advanced = self.control_card(advanced, &names, cx)?;
        let has_gains = ["red-gain", "green-gain", "blue-gain"]
            .iter()
            .any(|name| self.has_control(name));
        Some(advanced.when(has_gains, |e| {
            e.child(
                div()
                    .text_xs()
                    .text_color(rgb(MUTED))
                    .child("Select User color temperature to adjust RGB gains."),
            )
        }))
    }
    /// Adds a slider or choice group for each control the monitor reported, or `None` if it reported none.
    fn control_card(
        &self,
        mut result: Div,
        names: &[&'static str],
        cx: &mut Context<Self>,
    ) -> Option<Div> {
        if !names.iter().any(|name| self.has_control(name)) {
            return None;
        }
        for &name in names {
            if !self.has_control(name) {
                continue;
            }
            result = match self.sliders.get(name) {
                Some(slider) => result.child(slider.clone()),
                None => result.child(self.choice_group(name, cx)),
            };
        }
        Some(result)
    }
    fn profiles_card(&self, cx: &mut Context<Self>) -> Option<Div> {
        if self.config.profiles.is_empty() {
            return None;
        }
        let mut profiles = div().flex().flex_wrap().gap_2();
        for name in self.config.profiles.keys() {
            profiles = profiles.child(self.button(
                format!("profile-{name}"),
                name.clone(),
                Operation::Profile(name.clone()),
                cx,
            ));
        }
        Some(card("Profiles", "").child(profiles))
    }
    /// Two columns on wide windows. Stacked, everyday audio and input controls come before advanced color.
    fn columns(&self, wide: bool, cx: &mut Context<Self>) -> Div {
        let mut display_column = div()
            .min_w_0()
            .flex()
            .flex_col()
            .gap_4()
            .child(self.levels_card())
            .children(self.picture_mode_card(cx));
        let mut utility_column = div()
            .min_w_0()
            .flex()
            .flex_col()
            .gap_4()
            .child(self.audio_card(cx))
            .child(self.switch_card("input", "Input source", cx));
        if self.has_control("kvm") {
            utility_column = utility_column.child(self.switch_card("kvm", "KVM", cx));
        }
        utility_column = utility_column.children(self.comfort_card(cx));
        if let Some(advanced) = self.advanced_color_card(cx) {
            if wide {
                display_column = display_column.child(advanced);
            } else {
                utility_column = utility_column.child(advanced);
            }
        }
        utility_column = utility_column.children(self.profiles_card(cx));
        div()
            .w_full()
            .grid()
            .gap_4()
            .grid_cols(if wide { 2 } else { 1 })
            .child(display_column)
            .child(utility_column)
    }
}
fn run_operation(request: Request) -> Outcome {
    let displays = match displays::discover(Path::new(displays::DRM_ROOT)) {
        Ok(displays) => displays,
        Err(error) => {
            return Outcome {
                displays: Vec::new(),
                auto_bus: request.auto_bus,
                result: Err(error),
            };
        }
    };
    let selection = &request.selection;
    let explicit =
        selection.bus.is_some() || selection.monitor.is_some() || selection.display.is_some();
    let auto_bus = if explicit {
        Ok(None)
    } else {
        // The desktop always targets a specific bus; it never silently uses ddcutil's default.
        let connected: Vec<u32> = displays.iter().filter_map(|display| display.bus).collect();
        let refresh = matches!(request.operation, Operation::Refresh);
        ui_model::auto_bus(request.auto_bus, &connected, refresh)
    };
    match auto_bus {
        Ok(auto_bus) => {
            let result = connect_and_run(request, &displays, auto_bus);
            Outcome {
                displays,
                auto_bus,
                result,
            }
        }
        Err(error) => Outcome {
            displays,
            auto_bus: request.auto_bus,
            result: Err(error),
        },
    }
}
fn connect_and_run(
    request: Request,
    displays: &[Display],
    auto_bus: Option<u32>,
) -> Result<Snapshot> {
    let Request {
        mut selection,
        operation,
        capabilities: cached_capabilities,
        last_config,
        ..
    } = request;
    // A broken config only blocks profiles; other controls keep the last config that loaded.
    let (config, warning) = match Config::load() {
        Ok(config) => (config, None),
        Err(error) if !matches!(operation, Operation::Profile(_)) => (
            last_config,
            Some(format!(
                "Could not reload the config file; using the last loaded one: {error:#}"
            )),
        ),
        Err(error) => return Err(error),
    };
    if auto_bus.is_some() {
        selection.bus = auto_bus;
    }
    if selection.bus.is_none() && selection.monitor.is_none() && selection.display.is_none() {
        return Ok(Snapshot {
            capabilities: None,
            config,
            monitor: None,
            status: Ok(Status::new()),
            warning,
        });
    }
    let monitor = Monitor::connect(&selection, &config, displays)?;
    send(&monitor, &config, &operation)?;
    let capabilities = if matches!(operation, Operation::Refresh) || cached_capabilities.is_none() {
        monitor.transport.capabilities().ok()
    } else {
        cached_capabilities
    };
    let status = match monitor.control_status(capabilities.as_ref()) {
        Ok(status) => Ok(status),
        Err(error) => Err(read_back_failure(&operation, &error).ok_or(error)?),
    };
    Ok(Snapshot {
        capabilities,
        config,
        monitor: Some(monitor),
        status,
        warning,
    })
}
/// Performs the operation's writes. Successful updates need no notification.
fn send(monitor: &Monitor, config: &Config, operation: &Operation) -> Result<()> {
    match operation {
        Operation::Refresh => {}
        Operation::Switch { feature, value } => monitor.apply(&[Step {
            code: features::feature(monitor.benq, feature)?.code,
            value: *value,
            label: format!("{feature} 0x{value:02x}"),
        }])?,
        Operation::Write { feature, value } => monitor.set_named(feature, value)?,
        Operation::Profile(name) => {
            monitor.apply(&config.profile(name)?.plan(monitor.benq)?)?;
        }
    }
    Ok(())
}
/// Explains a failed read after a successful write, so the write is not reported as failed.
/// Returns `None` for a refresh, where the read is the whole operation.
fn read_back_failure(operation: &Operation, error: &anyhow::Error) -> Option<String> {
    let sent = match operation {
        Operation::Refresh => return None,
        Operation::Write { feature, .. } | Operation::Switch { feature, .. } => {
            ui_model::label(feature)
        }
        Operation::Profile(name) => format!("Profile {name}"),
    };
    Some(format!(
        "{sent} sent, but the monitor could not be read back: {error:#}. Refresh to see current values."
    ))
}
fn control(
    id: impl Into<SharedString>,
    label: String,
    selected: bool,
    enabled: bool,
) -> Stateful<Div> {
    div()
        .id(id.into())
        .focusable()
        .tab_index(0)
        .px_3()
        .py_2()
        .rounded_md()
        .border_1()
        .border_color(rgb(if selected { ACCENT } else { BORDER }))
        .bg(rgb(if selected {
            theme::SELECTED_CONTROL
        } else {
            theme::CONTROL
        }))
        .text_sm()
        .text_color(rgb(if selected {
            theme::SELECTED_TEXT
        } else {
            theme::TEXT
        }))
        .focus(|style| style.border_color(rgb(ACCENT)))
        .when(enabled, |e| {
            e.cursor_pointer()
                .hover(|style| style.bg(rgb(theme::HOVERED_CONTROL)))
        })
        .when(!enabled, |e| e.opacity(0.5).tab_stop(false))
        .child(label)
}
fn card(title: &str, description: &str) -> Div {
    div()
        .w_full()
        .p_4()
        .rounded_lg()
        .border_1()
        .border_color(rgb(BORDER))
        .bg(rgb(PANEL))
        .flex()
        .flex_col()
        .gap_3()
        .child(
            div()
                .flex()
                .flex_col()
                .gap_1()
                .child(
                    div()
                        .text_base()
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(title.to_string()),
                )
                .when(!description.is_empty(), |e| {
                    e.child(
                        div()
                            .text_sm()
                            .text_color(rgb(MUTED))
                            .child(description.to_string()),
                    )
                }),
        )
}
impl Render for Freepilot {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let wide = window.viewport_size().width >= px(TWO_COLUMN_MIN_WIDTH);
        let mut content = div()
            .w_full()
            .max_w(px(1000.))
            .flex()
            .flex_col()
            .gap_4()
            .child(self.header(cx))
            .when(self.monitor_picker_open && self.displays.len() > 1, |e| {
                e.child(self.monitor_picker(cx))
            });
        if self.monitor.is_some() {
            content = content.child(self.columns(wide, cx));
        } else if !self.busy && !self.error {
            content = content.child(card(
                "Connect a display",
                "Connect a DDC/CI-capable monitor, then refresh to load its controls.",
            ));
        }
        div()
            .relative()
            .size_full()
            .flex()
            .bg(rgb(BACKGROUND))
            .text_color(rgb(theme::TEXT))
            .font_family("sans-serif")
            .track_focus(&self.focus)
            .on_key_down(cx.listener(|view, event: &KeyDownEvent, window, cx| {
                match event.keystroke.key.as_str() {
                    "tab" => {
                        if event.keystroke.modifiers.shift {
                            window.focus_prev();
                        } else {
                            window.focus_next();
                        }
                        cx.stop_propagation();
                    }
                    "r" if !event.is_held && !event.keystroke.modifiers.modified() => {
                        view.perform(Operation::Refresh, cx)
                    }
                    "escape" => {
                        view.error = false;
                        view.pending_switch = None;
                        view.monitor_picker_open = false;
                        cx.notify();
                    }
                    _ => {}
                }
            }))
            .child(
                div()
                    .id("controls")
                    .flex_1()
                    .min_w_0()
                    .min_h_0()
                    .h_full()
                    .overflow_y_scroll()
                    .p_6()
                    .flex()
                    .flex_col()
                    .items_center()
                    .child(content.flex_none()),
            )
            .when(self.error, |root| root.child(self.error_toast(cx)))
    }
}
fn open_controls(view: &Entity<Freepilot>, cx: &mut App) -> Result<WindowHandle<Freepilot>> {
    let bounds = Bounds::centered(None, size(px(1000.), px(640.)), cx);
    cx.open_window(
        WindowOptions {
            window_bounds: Some(WindowBounds::Windowed(bounds)),
            window_min_size: Some(size(px(740.), px(560.))),
            app_id: Some("freepilot".into()),
            titlebar: Some(TitlebarOptions {
                title: Some("Freepilot".into()),
                ..Default::default()
            }),
            ..Default::default()
        },
        |window, cx| {
            window.focus(&view.read(cx).focus);
            view.clone()
        },
    )
}

pub fn run(selection: Selection) -> Result<()> {
    use crate::tray::{Event, FreepilotTray};
    use ksni::blocking::TrayMethods;

    Application::new().run(move |cx| {
        let view = cx.new(|cx| Freepilot::new(selection, cx));
        let window = match open_controls(&view, cx) {
            Ok(window) => window,
            Err(error) => {
                eprintln!("freepilot: Cannot open window: {error:#}");
                cx.quit();
                return;
            }
        };
        // GPUI's Linux event loop stops when its last window is destroyed.
        cx.on_window_closed(|cx| {
            if cx.windows().is_empty() {
                cx.quit();
            }
        })
        .detach();
        let (events, receiver) = async_channel::bounded(32);
        let startup = cx.background_executor().spawn(async move {
            FreepilotTray {
                events,
                state: crate::tray::State::default(),
            }
            .spawn()
        });
        cx.spawn(async move |cx| {
            match startup.await {
                Ok(handle) => {
                    let handle = std::sync::Arc::new(handle);
                    let _ = cx.update(|cx| {
                        view.update(cx, |view, cx| {
                            view.tray = Some(handle.clone());
                            view.update_tray(cx);
                        });
                        cx.on_app_quit(move |_| {
                            let _ = handle.shutdown();
                            async {}
                        })
                        .detach();
                    });
                }
                Err(error) => {
                    eprintln!("freepilot: Tray unavailable: {error}");
                    return;
                }
            }
            while let Ok(event) = receiver.recv().await {
                let quitting = event == Event::Quit;
                let result = cx.update(|cx| match event {
                    Event::Quit => cx.quit(),
                    Event::Open => {
                        let _ = window.update(cx, |_, window, _| window.activate_window());
                        cx.activate(true);
                    }
                    Event::Mode { name, revision } => {
                        view.update(cx, |view, cx| {
                            if !view.busy && view.tray_revision == revision {
                                view.perform(
                                    Operation::Write {
                                        feature: "picture-mode",
                                        value: name,
                                    },
                                    cx,
                                );
                            }
                        });
                    }
                });
                if result.is_err() || quitting {
                    return;
                }
            }
        })
        .detach();
        cx.activate(true);
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Operation, read_back_failure};

    #[test]
    fn read_back_failures_after_a_write_keep_the_write_and_ask_for_a_refresh() {
        let error = anyhow::anyhow!("i2c-5 timed out");
        let message = read_back_failure(
            &Operation::Write {
                feature: "brightness",
                value: "40".into(),
            },
            &error,
        )
        .unwrap();
        assert!(message.contains("Brightness sent"));
        assert!(message.contains("i2c-5 timed out"));
        assert!(message.contains("Refresh"));
        let profile = read_back_failure(&Operation::Profile("evening".into()), &error).unwrap();
        assert!(profile.contains("evening"));
    }

    #[test]
    fn a_failed_refresh_is_reported_as_a_plain_error() {
        assert_eq!(
            read_back_failure(&Operation::Refresh, &anyhow::anyhow!("timed out")),
            None
        );
    }
}
