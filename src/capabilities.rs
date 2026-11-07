use anyhow::{Result, ensure};
use serde::{Serialize, Serializer};
use std::collections::BTreeMap;

#[derive(Clone, Debug, Serialize)]
pub struct Capabilities {
    pub raw: String,
    pub groups: BTreeMap<String, String>,
    #[serde(serialize_with = "serialize_hex_codes")]
    pub vcp: BTreeMap<u8, Option<Vec<u16>>>,
}
/// Writes VCP codes as `0x10`-style keys, in code order.
fn serialize_hex_codes<S: Serializer>(
    vcp: &BTreeMap<u8, Option<Vec<u16>>>,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.collect_map(
        vcp.iter()
            .map(|(code, values)| (format!("0x{code:02x}"), values)),
    )
}
fn group_end(bytes: &[u8], start: usize) -> usize {
    let mut depth = 1;
    for (index, byte) in bytes.iter().enumerate().skip(start) {
        match byte {
            b'(' => depth += 1,
            b')' => {
                depth -= 1;
                if depth == 0 {
                    return index;
                }
            }
            _ => {}
        }
    }
    bytes.len()
}
fn pairs(bytes: &[u8]) -> Option<Vec<u16>> {
    let digits: Vec<_> = bytes
        .iter()
        .copied()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect();
    if !digits.len().is_multiple_of(2) {
        return None;
    }
    digits
        .chunks(2)
        .map(|pair| u16::from_str_radix(std::str::from_utf8(pair).ok()?, 16).ok())
        .collect()
}
pub fn parse(raw: &str) -> Capabilities {
    let bytes = raw.as_bytes();
    let mut position = 0;
    let mut groups = BTreeMap::<String, String>::new();
    while position < bytes.len() {
        if !bytes[position].is_ascii_alphabetic() && bytes[position] != b'_' {
            position += 1;
            continue;
        }
        let start = position;
        while position < bytes.len()
            && (bytes[position].is_ascii_alphanumeric() || bytes[position] == b'_')
        {
            position += 1;
        }
        let name = String::from_utf8_lossy(&bytes[start..position]).to_ascii_lowercase();
        while position < bytes.len() && bytes[position].is_ascii_whitespace() {
            position += 1;
        }
        if bytes.get(position) != Some(&b'(') {
            continue;
        }
        position += 1;
        let end = group_end(bytes, position);
        let content = String::from_utf8_lossy(&bytes[position..end])
            .trim()
            .to_string();
        groups
            .entry(name)
            .and_modify(|existing| {
                existing.push(' ');
                existing.push_str(&content);
            })
            .or_insert(content);
        position = end.saturating_add(1);
    }
    let mut vcp = BTreeMap::new();
    if let Some(text) = groups.get("vcp") {
        let bytes = text.as_bytes();
        let mut position = 0;
        while position + 1 < bytes.len() {
            let Some(code) =
                pairs(&bytes[position..position + 2]).and_then(|parsed| parsed.first().copied())
            else {
                position += 1;
                continue;
            };
            position += 2;
            while position < bytes.len() && bytes[position].is_ascii_whitespace() {
                position += 1;
            }
            if bytes.get(position) == Some(&b'(') {
                position += 1;
                let end = group_end(bytes, position);
                vcp.insert(code as u8, pairs(&bytes[position..end]));
                position = end.saturating_add(1);
            } else {
                vcp.entry(code as u8).or_insert(None);
            }
        }
    }
    Capabilities {
        raw: raw.into(),
        groups,
        vcp,
    }
}
impl Capabilities {
    pub fn check(&self, code: u8, value: u16, choice: bool) -> Result<()> {
        let entry = self.vcp.get(&code);
        ensure!(entry.is_some(), "Monitor does not list VCP 0x{code:02x}");
        if choice && let Some(Some(values)) = entry {
            ensure!(
                values.contains(&value),
                "Monitor does not list value 0x{value:02x} for VCP 0x{code:02x}"
            );
        }
        Ok(())
    }
}
