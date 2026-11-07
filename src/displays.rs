use crate::config::Alias;
use anyhow::{Result, bail, ensure};
use serde::Serialize;
use std::{collections::BTreeMap, fs, path::Path};

/// Where the kernel lists display connectors and their EDID and DDC buses.
pub const DRM_ROOT: &str = "/sys/class/drm";

#[derive(Clone, Debug, Default, Serialize)]
pub struct Display {
    pub connector: String,
    pub bus: Option<u32>,
    pub manufacturer: String,
    pub model: String,
    pub serial: String,
    pub numeric_serial: u32,
}
impl Display {
    pub fn benq(&self) -> bool {
        self.manufacturer == "BNQ"
            && self.model.split_whitespace().any(|word| {
                word.starts_with("RD") && word.as_bytes().get(2).is_some_and(u8::is_ascii_digit)
            })
    }
    pub fn short_connector(&self) -> &str {
        self.connector
            .split_once('-')
            .map_or(&self.connector, |(_, rest)| rest)
    }
    pub fn matches_serial(&self, serial: &str) -> bool {
        self.serial == serial
            || (self.numeric_serial != 0 && self.numeric_serial.to_string() == serial)
    }
}
pub fn parse_edid(data: &[u8]) -> Result<Display> {
    ensure!(data.len() >= 128, "EDID is shorter than 128 bytes");
    let block = &data[..128];
    ensure!(
        block[..8] == [0, 255, 255, 255, 255, 255, 255, 0],
        "Invalid EDID header"
    );
    ensure!(
        block.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte)) == 0,
        "Invalid EDID checksum"
    );
    let word = u16::from_be_bytes([block[8], block[9]]);
    let mut display = Display {
        manufacturer: [10, 5, 0]
            .into_iter()
            .map(|shift| char::from(b'@' + ((word >> shift) & 31) as u8))
            .collect(),
        numeric_serial: u32::from_le_bytes(block[12..16].try_into()?),
        ..Default::default()
    };
    for offset in [54, 72, 90, 108] {
        let descriptor = &block[offset..offset + 18];
        if descriptor[..3] != [0, 0, 0] {
            continue;
        }
        let text = String::from_utf8_lossy(&descriptor[5..])
            .trim_matches(['\0', '\n', ' '])
            .to_string();
        match descriptor[3] {
            0xfc => display.model = text,
            0xff => display.serial = text,
            _ => {}
        }
    }
    Ok(display)
}
pub fn discover(root: &Path) -> Result<Vec<Display>> {
    let mut displays = Vec::new();
    let entries = match fs::read_dir(root) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(displays),
        Err(error) => return Err(error.into()),
    };
    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        if fs::read_to_string(path.join("status"))
            .unwrap_or_default()
            .trim()
            != "connected"
        {
            continue;
        }
        let mut display = fs::read(path.join("edid"))
            .ok()
            .and_then(|data| parse_edid(&data).ok())
            .unwrap_or_default();
        display.connector = entry.file_name().to_string_lossy().into_owned();
        let bus_name = fs::canonicalize(path.join("ddc"))
            .ok()
            .and_then(|p| p.file_name().map(|n| n.to_string_lossy().into_owned()));
        let linked_bus = bus_name.and_then(|n| n.strip_prefix("i2c-").and_then(|n| n.parse().ok()));
        let mut buses: Vec<u32> = fs::read_dir(&path)?
            .filter_map(|e| e.ok())
            .filter_map(|e| e.file_name().to_str()?.strip_prefix("i2c-")?.parse().ok())
            .collect();
        buses.sort();
        let child_bus = buses.first().copied();
        // AMD DisplayPort connectors can link `ddc` to an unresponsive hardware
        // I2C bus while exposing the working I2C-over-AUX bus as a child.
        let is_displayport = display.short_connector().starts_with("DP-")
            || display.short_connector().starts_with("eDP-");
        display.bus = if is_displayport {
            child_bus.or(linked_bus)
        } else {
            linked_bus.or(child_bus)
        };
        displays.push(display);
    }
    displays.sort_by(|a, b| a.connector.cmp(&b.connector));
    Ok(displays)
}
/// Finds the one connected display that `selector` names.
///
/// An alias name matches only through the alias. Otherwise the first rule
/// that matches any display decides: serial, full connector, short connector,
/// then a case-insensitive part of the model name.
pub fn select<'a>(
    displays: &'a [Display],
    selector: &str,
    aliases: &BTreeMap<String, Alias>,
) -> Result<&'a Display> {
    ensure!(!selector.is_empty(), "Monitor selector is empty");
    if let Some(alias) = aliases.get(selector) {
        let matches = displays
            .iter()
            .filter(|display| alias_matches(alias, display))
            .collect();
        return only_match(selector, matches);
    }
    let rules: [fn(&Display, &str) -> bool; 4] = [
        |display, selector| display.matches_serial(selector),
        |display, selector| display.connector == selector,
        |display, selector| display.short_connector() == selector,
        |display, selector| {
            !display.model.is_empty()
                && display
                    .model
                    .to_lowercase()
                    .contains(&selector.to_lowercase())
        },
    ];
    for rule in rules {
        let matches: Vec<_> = displays
            .iter()
            .filter(|display| rule(display, selector))
            .collect();
        if !matches.is_empty() {
            return only_match(selector, matches);
        }
    }
    bail!("No connected monitor matches {selector:?}")
}
fn alias_matches(alias: &Alias, display: &Display) -> bool {
    alias
        .serial
        .as_ref()
        .is_none_or(|serial| display.matches_serial(serial))
        && alias.connector.as_ref().is_none_or(|connector| {
            *connector == display.connector || connector == display.short_connector()
        })
}
fn only_match<'a>(selector: &str, matches: Vec<&'a Display>) -> Result<&'a Display> {
    match matches.as_slice() {
        [] => bail!("No connected monitor matches {selector:?}"),
        [display] => Ok(display),
        _ => bail!(
            "{selector:?} matches several monitors: {}",
            matches
                .iter()
                .map(|display| display.connector.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}
