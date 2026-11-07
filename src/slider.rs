use crate::theme;
use gpui::{
    Bounds, Context, DispatchPhase, EventEmitter, FocusHandle, FontWeight, KeyDownEvent,
    KeyUpEvent, MouseButton, MouseDownEvent, MouseMoveEvent, MouseUpEvent, Pixels, Point,
    Subscription, Window, canvas, div, fill, point, prelude::*, px, rgb, size,
};

pub struct Changed(pub u16);
const TRACK_INSET: f32 = 9.;
#[derive(Default)]
struct Edit {
    value: Option<u16>,
    original: Option<u16>,
    editing: bool,
}
impl Edit {
    fn preview(&mut self, value: u16) {
        if !self.editing {
            self.original = self.value;
            self.editing = true;
        }
        self.value = Some(value);
    }
    fn finish(&mut self) -> Option<u16> {
        if !self.editing {
            return None;
        }
        self.editing = false;
        self.value.filter(|_| self.value != self.original)
    }
    fn cancel(&mut self) {
        if self.editing {
            self.value = self.original;
            self.editing = false;
        }
    }
}
#[derive(Clone, Copy, Debug)]
struct Range {
    min: u16,
    max: u16,
}
impl Range {
    fn clamp(self, value: u16) -> u16 {
        value.clamp(self.min, self.max)
    }
    fn progress(self, value: u16) -> f32 {
        f32::from(self.clamp(value) - self.min) / f32::from(self.max - self.min)
    }
    fn pointer_value(self, x: f32, left: f32, width: f32) -> u16 {
        if width <= 0. || !x.is_finite() {
            return self.min;
        }
        self.min
            + (((x - left) / width).clamp(0., 1.) * f32::from(self.max - self.min)).round() as u16
    }
    fn key_value(self, key: &str, value: u16, shift: bool) -> Option<u16> {
        let large_step = ((self.max - self.min) / 10).max(1);
        let step = if shift { large_step } else { 1 };
        Some(self.clamp(match key {
            "left" | "down" => value.saturating_sub(step),
            "right" | "up" => value.saturating_add(step),
            "pageup" => value.saturating_add(large_step),
            "pagedown" => value.saturating_sub(large_step),
            "home" => self.min,
            "end" => self.max,
            _ => return None,
        }))
    }
}
pub struct Slider {
    label: &'static str,
    edit: Edit,
    range: Range,
    percent: bool,
    enabled: bool,
    pending: bool,
    dragging: bool,
    bounds: Bounds<Pixels>,
    focus: FocusHandle,
    focus_subscription: Option<Subscription>,
}
impl EventEmitter<Changed> for Slider {}
impl Slider {
    pub fn new(label: &'static str, percent: bool, cx: &mut Context<Self>) -> Self {
        Self {
            label,
            edit: Edit::default(),
            range: Range { min: 0, max: 100 },
            percent,
            enabled: false,
            pending: false,
            dragging: false,
            bounds: Bounds::default(),
            focus: cx.focus_handle().tab_index(0),
            focus_subscription: None,
        }
    }
    pub fn begin_update(&mut self, cx: &mut Context<Self>) {
        self.pending = true;
        self.focus = self.focus.clone().tab_stop(false);
        self.edit.cancel();
        self.dragging = false;
        cx.notify();
    }
    pub fn synchronize(
        &mut self,
        value: Option<u16>,
        bounds: (u16, u16),
        enabled: bool,
        cx: &mut Context<Self>,
    ) {
        self.range = Range {
            min: bounds.0,
            max: bounds.1.max(bounds.0.saturating_add(1)),
        };
        self.edit = Edit {
            value: value.filter(|v| (self.range.min..=self.range.max).contains(v)),
            ..Default::default()
        };
        self.dragging = false;
        self.pending = false;
        self.enabled = enabled && self.edit.value.is_some();
        self.focus = self.focus.clone().tab_stop(self.enabled);
        cx.notify();
    }
    fn preview_pointer(&mut self, position: Point<Pixels>, cx: &mut Context<Self>) {
        self.edit.preview(self.range.pointer_value(
            position.x.into(),
            (self.bounds.origin.x + px(TRACK_INSET)).into(),
            (self.bounds.size.width - px(TRACK_INSET * 2.)).into(),
        ));
        cx.notify();
    }
    fn finish(&mut self, cx: &mut Context<Self>) {
        self.dragging = false;
        if let Some(value) = self.edit.finish() {
            cx.emit(Changed(value));
        }
        cx.notify();
    }
}
impl Render for Slider {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        // `on_focus_out` needs a `Window`, which the slider first sees here.
        if self.focus_subscription.is_none() {
            self.focus_subscription =
                Some(
                    cx.on_focus_out(&self.focus.clone(), window, |slider, _, _, cx| {
                        slider.dragging = false;
                        slider.edit.cancel();
                        cx.notify();
                    }),
                );
        }
        let entity = cx.entity();
        let value = self.edit.value;
        let range = self.range;
        let enabled = self.enabled;
        let interactive = enabled && !self.pending;
        let focused = self.focus.is_focused(window);
        let dragging = self.dragging;
        div()
            .flex()
            .items_center()
            .gap_3()
            .w_full()
            .child(
                div()
                    .w(px(74.))
                    .flex_none()
                    .text_sm()
                    .font_weight(FontWeight::MEDIUM)
                    .child(self.label),
            )
            .child(
                div()
                    .id("slider")
                    .flex_1()
                    .min_w(px(60.))
                    .h(px(32.))
                    .rounded_md()
                    .border_1()
                    .border_color(rgb(if focused { theme::ACCENT } else { theme::PANEL }))
                    .track_focus(&self.focus)
                    .tab_index(0)
                    .when(interactive, |e| e.cursor_pointer())
                    .when(!enabled, |e| e.opacity(0.45))
                    .on_mouse_down(
                        MouseButton::Left,
                        cx.listener(|slider, event: &MouseDownEvent, window, cx| {
                            if !slider.enabled || slider.pending {
                                return;
                            }
                            window.focus(&slider.focus);
                            slider.dragging = true;
                            slider.preview_pointer(event.position, cx);
                            cx.stop_propagation();
                        }),
                    )
                    .on_key_down(cx.listener(|slider, event: &KeyDownEvent, _, cx| {
                        if event.keystroke.key == "escape" {
                            // An idle slider lets Escape reach the window to close dialogs.
                            if slider.edit.editing || slider.dragging {
                                slider.dragging = false;
                                slider.edit.cancel();
                                cx.notify();
                                cx.stop_propagation();
                            }
                            return;
                        }
                        if slider.enabled
                            && !slider.pending
                            && let Some(value) = slider.range.key_value(
                                &event.keystroke.key,
                                slider.edit.value.unwrap_or(0),
                                event.keystroke.modifiers.shift,
                            )
                        {
                            slider.edit.preview(value);
                            cx.notify();
                            cx.stop_propagation();
                        }
                    }))
                    .on_key_up(cx.listener(|slider, event: &KeyUpEvent, _, cx| {
                        if slider.enabled
                            && !slider.pending
                            && slider
                                .range
                                .key_value(&event.keystroke.key, 0, false)
                                .is_some()
                        {
                            slider.finish(cx);
                            cx.stop_propagation();
                        }
                    }))
                    .child(
                        canvas(
                            move |bounds, _, cx| {
                                entity.update(cx, |slider, _| slider.bounds = bounds);
                            },
                            {
                                let entity = cx.entity();
                                move |bounds, _, window, _| {
                                    let left = bounds.origin.x + px(TRACK_INSET);
                                    let width =
                                        (bounds.size.width - px(TRACK_INSET * 2.)).max(px(1.));
                                    let center = bounds.origin.y + bounds.size.height / 2.;
                                    let progress =
                                        width * (range.progress(value.unwrap_or(range.min)));
                                    window.paint_quad(
                                        fill(
                                            Bounds::new(
                                                point(left, center - px(3.)),
                                                size(width, px(6.)),
                                            ),
                                            rgb(theme::TRACK),
                                        )
                                        .corner_radii(px(3.)),
                                    );
                                    window.paint_quad(
                                        fill(
                                            Bounds::new(
                                                point(left, center - px(3.)),
                                                size(progress, px(6.)),
                                            ),
                                            rgb(theme::ACCENT),
                                        )
                                        .corner_radii(px(3.)),
                                    );
                                    if value.is_some() {
                                        window.paint_quad(
                                            fill(
                                                Bounds::new(
                                                    point(
                                                        left + progress - px(8.),
                                                        center - px(8.),
                                                    ),
                                                    size(px(16.), px(16.)),
                                                ),
                                                rgb(if dragging { 0xffffff } else { theme::THUMB }),
                                            )
                                            .corner_radii(px(8.)),
                                        );
                                    }
                                    let moving = entity.downgrade();
                                    window.on_mouse_event(
                                        move |event: &MouseMoveEvent, phase, _, cx| {
                                            if phase == DispatchPhase::Bubble {
                                                let _ = moving.update(cx, |slider, cx| {
                                                    if slider.dragging {
                                                        if event.pressed_button
                                                            == Some(MouseButton::Left)
                                                        {
                                                            slider.preview_pointer(
                                                                event.position,
                                                                cx,
                                                            );
                                                        } else {
                                                            slider.dragging = false;
                                                            slider.edit.cancel();
                                                            cx.notify();
                                                        }
                                                    }
                                                });
                                            }
                                        },
                                    );
                                    let released = entity.downgrade();
                                    window.on_mouse_event(
                                        move |event: &MouseUpEvent, phase, _, cx| {
                                            if phase == DispatchPhase::Bubble
                                                && event.button == MouseButton::Left
                                            {
                                                let _ = released.update(cx, |slider, cx| {
                                                    if slider.dragging {
                                                        slider.preview_pointer(event.position, cx);
                                                        slider.finish(cx);
                                                        cx.stop_propagation();
                                                    }
                                                });
                                            }
                                        },
                                    );
                                }
                            },
                        )
                        .size_full(),
                    ),
            )
            .child(
                div()
                    .w(px(44.))
                    .flex_none()
                    .text_right()
                    .text_sm()
                    .text_color(rgb(if enabled {
                        theme::TEXT
                    } else {
                        theme::DISABLED_TEXT
                    }))
                    .child(value.map_or("—".into(), |v| {
                        if self.percent {
                            format!("{v}%")
                        } else {
                            format!("{v}/{}", self.range.max)
                        }
                    })),
            )
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dragging_clamps_to_the_track_and_only_commits_once() {
        assert_eq!(Range { min: 0, max: 100 }.pointer_value(-10., 0., 200.), 0);
        assert_eq!(
            Range { min: 0, max: 100 }.pointer_value(250., 0., 200.),
            100
        );
        assert_eq!(Range { min: 0, max: 100 }.pointer_value(150., 0., 200.), 75);
        let mut edit = Edit {
            value: Some(30),
            ..Default::default()
        };
        for value in 31..=80 {
            edit.preview(value);
        }
        assert_eq!(edit.finish(), Some(80));
        assert_eq!(edit.finish(), None);
        edit.preview(80);
        assert_eq!(edit.finish(), None);
        edit.preview(20);
        edit.cancel();
        assert_eq!(edit.value, Some(80));
        assert_eq!(edit.finish(), None);
    }
    #[test]
    fn native_ranges_use_their_own_endpoints_and_step_sizes() {
        let sharpness = Range { min: 0, max: 10 };
        assert_eq!(sharpness.pointer_value(100., 0., 200.), 5);
        assert_eq!(sharpness.key_value("end", 6, false), Some(10));
        assert_eq!(sharpness.key_value("right", 9, true), Some(10));
        let night = Range { min: 1, max: 10 };
        assert_eq!(night.pointer_value(-10., 0., 200.), 1);
        assert_eq!(night.pointer_value(300., 0., 200.), 10);
        assert_eq!(night.key_value("left", 1, false), Some(1));
        assert_eq!(night.progress(1), 0.);
        assert_eq!(night.progress(10), 1.);
    }
    #[test]
    fn keyboard_adjustments_respect_bounds_and_step_sizes() {
        assert_eq!(
            Range { min: 0, max: 100 }.key_value("left", 0, false),
            Some(0)
        );
        assert_eq!(
            Range { min: 0, max: 100 }.key_value("right", 100, false),
            Some(100)
        );
        assert_eq!(
            Range { min: 0, max: 100 }.key_value("right", 40, true),
            Some(50)
        );
        assert_eq!(
            Range { min: 0, max: 100 }.key_value("end", 40, false),
            Some(100)
        );
        assert_eq!(
            Range { min: 0, max: 100 }.key_value("home", 40, false),
            Some(0)
        );
    }
}
