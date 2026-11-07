use anyhow::{Context, Result, bail};
use serde::Serialize;
use std::{
    io::Read,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Reading {
    pub code: u8,
    pub value: Option<u16>,
    pub max: Option<u16>,
}
#[derive(Clone, Debug, Default)]
pub struct Ddcutil {
    pub bus: Option<u32>,
    pub display: Option<u32>,
}
/// What a finished ddcutil process printed and whether it exited successfully.
#[derive(Clone, Debug, Default)]
pub struct CommandOutput {
    pub succeeded: bool,
    pub stdout: String,
    pub stderr: String,
}
impl CommandOutput {
    fn failure(&self) -> anyhow::Error {
        let detail = if self.stderr.trim().is_empty() {
            self.stdout.trim()
        } else {
            self.stderr.trim()
        };
        anyhow::anyhow!("ddcutil failed: {detail}")
    }
}
/// Decides whether a `getvcp --terse` run produced usable readings.
///
/// ddcutil keeps reading after a feature fails, prints `VCP xx ERR` (or no `VCP` line
/// for an unreadable feature), and then exits non-zero. A failed run is therefore
/// accepted when it printed a line for at least one requested code; the other codes
/// read as unknown.
pub fn readings_from(codes: &[u8], output: &CommandOutput) -> Result<Vec<Reading>> {
    let readings = parse_terse(&output.stdout)?;
    let read_a_requested_code = readings.iter().any(|reading| codes.contains(&reading.code));
    if output.succeeded || read_a_requested_code {
        return Ok(readings);
    }
    Err(output.failure())
}
impl Ddcutil {
    fn execute(&self, arguments: &[String]) -> Result<CommandOutput> {
        let mut command = Command::new("ddcutil");
        if let Some(bus) = self.bus {
            command.args(["--bus", &bus.to_string()]);
        }
        if let Some(display) = self.display {
            command.args(["--display", &display.to_string()]);
        }
        let mut child = command
            .args(arguments)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .context("Cannot start ddcutil; install it and check i2c permissions")?;
        // Drain both pipes while waiting so verbose diagnostics cannot fill a pipe.
        let mut stdout = child.stdout.take().context("Missing ddcutil stdout")?;
        let mut stderr = child.stderr.take().context("Missing ddcutil stderr")?;
        let stdout_reader = thread::spawn(move || {
            let mut bytes = Vec::new();
            stdout.read_to_end(&mut bytes).map(|_| bytes)
        });
        let stderr_reader = thread::spawn(move || {
            let mut bytes = Vec::new();
            stderr.read_to_end(&mut bytes).map(|_| bytes)
        });
        let deadline = Instant::now() + Duration::from_secs(20);
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) => {}
                Err(error) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(error).context("Cannot wait for ddcutil");
                }
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            thread::sleep(Duration::from_millis(20));
        };
        let stdout = String::from_utf8_lossy(
            &stdout_reader
                .join()
                .map_err(|_| anyhow::anyhow!("Output reader failed"))??,
        )
        .into_owned();
        let stderr = String::from_utf8_lossy(
            &stderr_reader
                .join()
                .map_err(|_| anyhow::anyhow!("Error reader failed"))??,
        )
        .into_owned();
        let Some(status) = status else {
            if arguments.first().is_some_and(|command| command == "setvcp") {
                bail!("ddcutil timed out; a write may have applied and was not retried");
            }
            bail!("ddcutil timed out");
        };
        Ok(CommandOutput {
            succeeded: status.success(),
            stdout,
            stderr,
        })
    }
    fn run(&self, arguments: &[String]) -> Result<String> {
        let output = self.execute(arguments)?;
        if !output.succeeded {
            return Err(output.failure());
        }
        Ok(output.stdout)
    }
    pub fn get(&self, codes: &[u8]) -> Result<Vec<Reading>> {
        let mut arguments = vec!["getvcp".into(), "--terse".into()];
        arguments.extend(codes.iter().map(|code| format!("0x{code:02x}")));
        readings_from(codes, &self.execute(&arguments)?)
    }
    pub fn set(&self, code: u8, value: u16) -> Result<()> {
        self.run(&["setvcp".into(), format!("0x{code:02x}"), value.to_string()])?;
        thread::sleep(Duration::from_millis(crate::features::write_delay(code)));
        Ok(())
    }
    pub fn capabilities(&self) -> Result<crate::capabilities::Capabilities> {
        let output = self.run(&["capabilities".into(), "--terse".into()])?;
        let raw = output
            .lines()
            .find_map(|line| {
                line.split_once("capabilities string:")
                    .map(|(_, raw)| raw.trim())
            })
            .context("ddcutil returned no capability string")?;
        Ok(crate::capabilities::parse(raw))
    }
}
/// Parses a hex field of terse output: a bare code such as `DC`, an `x`-prefixed
/// value such as `x30`, or a `0x`-prefixed value.
fn hex(text: &str) -> Result<u16> {
    let digits = text
        .strip_prefix("0x")
        .or_else(|| text.strip_prefix('x'))
        .unwrap_or(text);
    Ok(u16::from_str_radix(digits, 16)?)
}
pub fn parse_terse(output: &str) -> Result<Vec<Reading>> {
    let mut readings = Vec::new();
    for line in output.lines() {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.first() != Some(&"VCP") {
            continue;
        }
        let code = u8::try_from(hex(fields.get(1).context("Missing VCP code")?)?)?;
        let (value, max) = match fields.as_slice() {
            [_, _, "C", value, max] => (Some(value.parse()?), Some(max.parse()?)),
            [_, _, "SNC", value] => (Some(hex(value)?), None),
            [_, _, "CNC", _, _, high, low] => {
                let high = u8::try_from(hex(high)?)?;
                let low = u8::try_from(hex(low)?)?;
                (Some(u16::from_be_bytes([high, low])), None)
            }
            _ => (None, None),
        };
        readings.push(Reading { code, value, max });
    }
    Ok(readings)
}
