pub mod capabilities;
pub mod config;
pub mod displays;
pub mod features;
pub mod transport;

use anyhow::{Context, Result, ensure};
use config::{Config, Step};
use features::Kind;
use serde::{Serialize, Serializer};
use std::collections::BTreeMap;
use transport::Ddcutil;

/// One VCP feature as reported to users: the wire reading plus what Freepilot knows about the code.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct FeatureReading {
    pub code: u8,
    pub name: Option<&'static str>,
    #[serde(serialize_with = "serialize_kind")]
    pub kind: Option<Kind>,
    pub value: Option<u16>,
    pub max: Option<u16>,
    pub label: Option<&'static str>,
}
fn serialize_kind<S: Serializer>(kind: &Option<Kind>, serializer: S) -> Result<S::Ok, S::Error> {
    match kind {
        Some(kind) => kind.serialize(serializer),
        None => serializer.serialize_str("unknown"),
    }
}
impl FeatureReading {
    /// Describes `code` for a monitor; `wire` is `None` when the code was not read.
    pub fn new(benq: bool, code: u8, wire: Option<&transport::Reading>) -> Self {
        let feature = features::features(benq)
            .iter()
            .find(|feature| feature.code == code);
        let value = wire.and_then(|reading| reading.value);
        let label = feature
            .and_then(|feature| {
                feature
                    .values
                    .iter()
                    .find(|(_, wire_value)| Some(*wire_value) == value)
            })
            .map(|(label, _)| *label);
        Self {
            code,
            name: feature.map(|feature| feature.name),
            kind: feature.map(|feature| feature.kind),
            value,
            max: wire.and_then(|reading| reading.max),
            label,
        }
    }
}
pub type Status = BTreeMap<&'static str, FeatureReading>;

/// Refuses a step whose value is above the maximum the monitor reported for its code.
/// Step labels already name the value, as in `sharpness 50`.
/// Codes without a reading or without a reported maximum are not checked.
pub fn check_reported_maxima(steps: &[Step], readings: &[transport::Reading]) -> Result<()> {
    for step in steps {
        let reported_max = readings
            .iter()
            .find(|reading| reading.code == step.code)
            .and_then(|reading| reading.max);
        if let Some(max) = reported_max {
            ensure!(
                step.value <= max,
                "{} exceeds the monitor's maximum {max}",
                step.label
            );
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Default)]
pub struct Selection {
    pub bus: Option<u32>,
    pub display: Option<u32>,
    pub monitor: Option<String>,
    pub model: Option<String>,
    pub strict: bool,
}
#[derive(Clone, Debug)]
pub struct Monitor {
    pub transport: Ddcutil,
    pub benq: bool,
    pub strict: bool,
}
impl Monitor {
    pub fn connect(
        selection: &Selection,
        config: &Config,
        displays: &[displays::Display],
    ) -> Result<Self> {
        let display = if let Some(selector) = &selection.monitor {
            Some(displays::select(displays, selector, &config.monitors)?)
        } else if let Some(bus) = selection.bus {
            displays.iter().find(|display| display.bus == Some(bus))
        } else if selection.display.is_none()
            && displays
                .iter()
                .filter(|display| display.bus.is_some())
                .count()
                == 1
        {
            displays.iter().find(|display| display.bus.is_some())
        } else {
            None
        };
        let alias = selection
            .monitor
            .as_ref()
            .and_then(|name| config.monitors.get(name));
        let model = selection
            .model
            .as_ref()
            .or_else(|| alias.and_then(|alias| alias.model.as_ref()));
        let benq = match model.map(String::as_str) {
            Some("benq-rd") => true,
            Some("mccs") => false,
            None => display.is_some_and(displays::Display::benq),
            _ => anyhow::bail!("Unknown model"),
        };
        if selection.monitor.is_some() {
            ensure!(
                display.is_some_and(|display| display.bus.is_some()),
                "Selected monitor has no DDC bus; pass --bus"
            );
        }
        Ok(Self {
            transport: Ddcutil {
                bus: selection
                    .bus
                    .or_else(|| display.and_then(|display| display.bus)),
                display: selection.display,
            },
            benq,
            strict: selection.strict,
        })
    }
    fn feature_kind(&self, code: u8) -> Option<Kind> {
        features::features(self.benq)
            .iter()
            .find(|feature| feature.code == code)
            .map(|feature| feature.kind)
    }
    pub fn readings(&self, codes: &[u8]) -> Result<Vec<FeatureReading>> {
        let wire_readings = self.transport.get(codes)?;
        Ok(codes
            .iter()
            .map(|code| {
                let wire = wire_readings.iter().find(|reading| reading.code == *code);
                FeatureReading::new(self.benq, *code, wire)
            })
            .collect())
    }
    pub fn status(&self) -> Result<Status> {
        let names = if self.benq {
            vec![
                "picture-mode",
                "input",
                "brightness",
                "contrast",
                "volume",
                "mute",
            ]
        } else {
            vec!["input", "brightness", "contrast", "volume", "mute"]
        };
        let codes = names
            .iter()
            .map(|name| features::feature(self.benq, name).map(|feature| feature.code))
            .collect::<Result<Vec<_>>>()?;
        let readings = self.readings(&codes)?;
        Ok(names.into_iter().zip(readings).collect())
    }
    /// Adds the extra controls the capabilities list, read in one batch after the basic status.
    /// If that batch fails, every extra control reads as unknown so the basic status still shows.
    pub fn control_status(
        &self,
        capabilities: Option<&capabilities::Capabilities>,
    ) -> Result<Status> {
        let mut status = self.status()?;
        let listed_features: Vec<_> = features::EXTRA_CONTROLS
            .iter()
            .filter_map(|name| features::feature(self.benq, name).ok())
            .filter(|feature| capabilities.is_some_and(|caps| caps.vcp.contains_key(&feature.code)))
            .collect();
        if listed_features.is_empty() {
            return Ok(status);
        }
        let codes: Vec<_> = listed_features.iter().map(|feature| feature.code).collect();
        let readings = self.readings(&codes).unwrap_or_else(|_| {
            codes
                .iter()
                .map(|code| FeatureReading::new(self.benq, *code, None))
                .collect()
        });
        for (feature, reading) in listed_features.into_iter().zip(readings) {
            status.insert(feature.name, reading);
        }
        Ok(status)
    }
    /// With `strict`, checks every step against the capabilities and the reported maxima
    /// before the first write.
    pub fn apply(&self, steps: &[Step]) -> Result<()> {
        if self.strict {
            let caps = self.transport.capabilities()?;
            for step in steps {
                let is_choice = self.feature_kind(step.code) == Some(Kind::Choice);
                caps.check(step.code, step.value, is_choice)?;
            }
            let continuous_codes: Vec<_> = steps
                .iter()
                .map(|step| step.code)
                .filter(|code| self.feature_kind(*code) == Some(Kind::Continuous))
                .collect();
            if !continuous_codes.is_empty() {
                let readings = self
                    .transport
                    .get(&continuous_codes)
                    .context("Cannot read the monitor's maximum values")?;
                check_reported_maxima(steps, &readings)?;
            }
        }
        for (index, step) in steps.iter().enumerate() {
            if let Err(error) = self.transport.set(step.code, step.value) {
                anyhow::bail!(
                    "{} failed and may have applied: {error:#}; sent: {}; not attempted: {}",
                    step.label,
                    steps[..index]
                        .iter()
                        .map(|sent| sent.label.as_str())
                        .collect::<Vec<_>>()
                        .join(", "),
                    steps[index + 1..]
                        .iter()
                        .map(|pending| pending.label.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                );
            }
        }
        Ok(())
    }
    pub fn set_named(&self, name: &str, value: &str) -> Result<()> {
        let (code, wire_value) = features::setting(self.benq, name, value)?;
        self.apply(&[Step {
            code,
            value: wire_value,
            label: format!("{name} {value}"),
        }])
    }
    pub fn save_profile(&self, name: &str) -> Result<String> {
        let status = self.status()?;
        let mut text = format!("[profiles.{}]\n", serde_json::to_string(name)?);
        for (key, reading) in status {
            let value = if reading.kind == Some(Kind::Choice) {
                reading.label.map(|label| format!("{label:?}"))
            } else {
                reading.value.map(|value| value.to_string())
            };
            match value {
                Some(value) => text.push_str(&format!(
                    "{}{key} = {value}\n",
                    if key == "input" { "# " } else { "" }
                )),
                None => text.push_str(&format!("# {key}: unreadable or unknown value\n")),
            }
        }
        Ok(text)
    }
}
