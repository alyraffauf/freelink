use crate::features::{self, Kind};
use anyhow::{Context, Result, bail, ensure};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, ffi::OsString, path::PathBuf};

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    #[serde(default)]
    pub monitors: BTreeMap<String, Alias>,
    #[serde(default)]
    pub profiles: BTreeMap<String, Profile>,
}
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Alias {
    pub serial: Option<String>,
    pub connector: Option<String>,
    pub model: Option<String>,
}
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Profile {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub monitor: Option<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub vcp: BTreeMap<String, u16>,
    #[serde(flatten)]
    pub settings: BTreeMap<String, toml::Value>,
}
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Step {
    pub code: u8,
    pub value: u16,
    pub label: String,
}

enum PlanEntry {
    Named(&'static str),
    RawCodes,
}
/// Profile keys in the order `plan` writes them. Picture mode goes first
/// because changing it resets levels on most monitors. Input goes last because
/// it may switch the monitor away from this machine.
const PROFILE_PLAN: &[PlanEntry] = &[
    PlanEntry::Named("picture-mode"),
    PlanEntry::Named("brightness"),
    PlanEntry::Named("contrast"),
    PlanEntry::Named("sharpness"),
    PlanEntry::Named("volume"),
    PlanEntry::Named("mute"),
    PlanEntry::RawCodes,
    PlanEntry::Named("input"),
];
/// Raw codes a profile may not write: reset and restore commands, and
/// settings that disrupt the session or have a validated named key.
const DENIED_RAW_CODES: &[u8] = &[
    0x04, // restore factory defaults
    0x05, // restore brightness and contrast defaults
    0x06, // restore geometry defaults
    0x08, // restore colour defaults
    0x0A, // restore TV defaults
    0x60, // input source; use the `input` key
    0xB0, // store or restore user settings
    0xD6, // power mode
    0xDC, // picture mode; use the `picture-mode` key
    0xE4, // KVM switch
];

/// Returns the config file path from `$FREEPILOT_CONFIG`, `$XDG_CONFIG_HOME`,
/// or `$HOME/.config`, in that order.
pub fn path() -> Result<PathBuf> {
    resolve_path(
        std::env::var_os("FREEPILOT_CONFIG"),
        std::env::var_os("XDG_CONFIG_HOME"),
        std::env::var_os("HOME"),
    )
}
fn resolve_path(
    explicit: Option<OsString>,
    xdg_config_home: Option<OsString>,
    home: Option<OsString>,
) -> Result<PathBuf> {
    if let Some(path) = explicit.filter(|path| !path.is_empty()) {
        return Ok(path.into());
    }
    // The XDG base directory spec says to ignore relative paths.
    let absolute = |value: Option<OsString>| value.map(PathBuf::from).filter(|p| p.is_absolute());
    let base = absolute(xdg_config_home)
        .or_else(|| absolute(home).map(|home| home.join(".config")))
        .context("Cannot find the config file: set FREEPILOT_CONFIG, XDG_CONFIG_HOME, or HOME")?;
    Ok(base.join("freepilot/config.toml"))
}

impl Config {
    /// Reads and validates the config file. A missing file is an empty config.
    pub fn load() -> Result<Self> {
        let path = path()?;
        let text = match std::fs::read_to_string(&path) {
            Ok(text) => text,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(Self::default());
            }
            Err(error) => return Err(error).with_context(|| path.display().to_string()),
        };
        Self::from_toml(&text).with_context(|| path.display().to_string())
    }
    pub fn from_toml(text: &str) -> Result<Self> {
        let config: Self = toml::from_str(text)?;
        for (name, alias) in &config.monitors {
            alias
                .validate()
                .with_context(|| format!("monitor alias {name:?}"))?;
        }
        for (name, profile) in &config.profiles {
            profile
                .validate()
                .with_context(|| format!("profile {name:?}"))?;
        }
        Ok(config)
    }
    pub fn profile(&self, name: &str) -> Result<&Profile> {
        self.profiles
            .get(name)
            .with_context(|| format!("No profile named {name:?}"))
    }
}
impl Alias {
    fn validate(&self) -> Result<()> {
        ensure!(
            self.serial.is_some() || self.connector.is_some(),
            "needs serial or connector"
        );
        ensure!(self.serial.as_deref() != Some(""), "serial is empty");
        ensure!(self.connector.as_deref() != Some(""), "connector is empty");
        if let Some(model) = &self.model {
            ensure!(
                ["benq-rd", "mccs"].contains(&model.as_str()),
                "Unknown model {model}"
            );
        }
        Ok(())
    }
}
impl Profile {
    /// Checks every key and value that does not depend on the monitor model.
    pub fn validate(&self) -> Result<()> {
        ensure!(
            !self.settings.is_empty() || !self.vcp.is_empty(),
            "Profile sets nothing"
        );
        for (name, value) in &self.settings {
            let known = PROFILE_PLAN
                .iter()
                .any(|entry| matches!(entry, PlanEntry::Named(key) if key == name));
            ensure!(known, "Unknown profile setting {name}");
            // The BenQ RD table is a superset of the MCCS one, with the same kinds.
            match features::feature(true, name)?.kind {
                Kind::Continuous => {
                    let (min, max) = features::level_bounds(name);
                    ensure!(
                        value
                            .as_integer()
                            .is_some_and(|v| (i64::from(min)..=i64::from(max)).contains(&v)),
                        "{name} must be an integer between {min} and {max}"
                    );
                }
                Kind::Choice => ensure!(value.as_str().is_some(), "{name} must be a string"),
                Kind::Raw => bail!("{name} is not a profile setting"),
            }
        }
        let mut seen = std::collections::BTreeSet::new();
        for key in self.vcp.keys() {
            let code = raw_code(key)?;
            ensure!(seen.insert(code), "Duplicate raw VCP code 0x{code:02x}");
            ensure!(
                !DENIED_RAW_CODES.contains(&code),
                "Profile cannot set disruptive raw VCP 0x{code:02x}"
            );
            ensure!(
                !self
                    .settings
                    .keys()
                    .any(|name| features::feature(true, name).is_ok_and(|f| f.code == code)),
                "Profile sets VCP 0x{code:02x} twice"
            );
        }
        Ok(())
    }
    pub fn plan(&self, benq: bool) -> Result<Vec<Step>> {
        self.validate()?;
        let mut steps = Vec::new();
        for entry in PROFILE_PLAN {
            match entry {
                PlanEntry::Named(name) => {
                    if let Some(value) = self.settings.get(*name) {
                        steps.push(named_step(benq, name, value)?);
                    }
                }
                PlanEntry::RawCodes => {
                    let mut raw = Vec::new();
                    for (key, value) in &self.vcp {
                        let code = raw_code(key)?;
                        raw.push(Step {
                            code,
                            value: *value,
                            label: format!("vcp 0x{code:02x} = {value}"),
                        });
                    }
                    raw.sort_by_key(|step| step.code);
                    steps.extend(raw);
                }
            }
        }
        Ok(steps)
    }
}
fn named_step(benq: bool, name: &str, value: &toml::Value) -> Result<Step> {
    let text = value
        .as_str()
        .map(str::to_string)
        .unwrap_or_else(|| value.to_string());
    let (code, value) = features::setting(benq, name, &text)?;
    Ok(Step {
        code,
        value,
        label: format!("{name} {text}"),
    })
}
fn raw_code(key: &str) -> Result<u8> {
    features::number(key)
        .ok()
        .and_then(|number| u8::try_from(number).ok())
        .with_context(|| format!("raw VCP key {key:?} must be a code from 0x00 to 0xff"))
}

#[cfg(test)]
mod tests {
    use super::resolve_path;
    use std::path::PathBuf;

    #[test]
    fn config_path_ignores_relative_bases_and_never_falls_back_to_cwd() {
        let path = |explicit: Option<&str>, xdg: Option<&str>, home: Option<&str>| {
            resolve_path(
                explicit.map(Into::into),
                xdg.map(Into::into),
                home.map(Into::into),
            )
        };
        assert_eq!(
            path(Some("custom.toml"), Some("/xdg"), Some("/home/a")).unwrap(),
            PathBuf::from("custom.toml")
        );
        assert_eq!(
            path(None, Some("relative"), Some("/home/a")).unwrap(),
            PathBuf::from("/home/a/.config/freepilot/config.toml")
        );
        assert_eq!(
            path(None, Some("/xdg"), None).unwrap(),
            PathBuf::from("/xdg/freepilot/config.toml")
        );
        assert!(path(None, Some("relative"), Some("")).is_err());
        assert!(path(None, None, None).is_err());
    }
}
