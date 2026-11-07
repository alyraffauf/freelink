use anyhow::Result;
use clap::{Args, Parser, Subcommand};
use freepilot::{
    Monitor, Selection,
    config::{Config, Profile, Step},
    displays, features,
};
use std::path::Path;

#[cfg(feature = "gui")]
mod gui;
#[cfg(feature = "gui")]
mod slider;
#[cfg(feature = "gui")]
mod theme;
#[cfg(feature = "gui")]
mod tray;
#[cfg(feature = "gui")]
mod ui_model;
#[derive(Parser)]
#[command(
    version,
    about = "Control monitors over DDC/CI. Opens the desktop app without a command."
)]
struct Cli {
    #[arg(long, global = true)]
    json: bool,
    #[command(flatten)]
    target: Target,
    #[command(subcommand)]
    command: Option<Command>,
}
#[derive(Args)]
#[group(multiple = false)]
struct TargetSelector {
    #[arg(long)]
    bus: Option<u32>,
    #[arg(long)]
    display: Option<u32>,
    #[arg(long)]
    monitor: Option<String>,
}
#[derive(Args)]
struct Target {
    #[command(flatten)]
    selector: TargetSelector,
    #[arg(long,value_parser=["benq-rd","mccs"])]
    model: Option<String>,
    #[arg(long)]
    strict: bool,
}
#[derive(Subcommand)]
enum Command {
    Gui,
    List,
    Status,
    Codes,
    Capabilities,
    Get {
        #[arg(required = true)]
        features: Vec<String>,
    },
    Set {
        feature: String,
        value: String,
    },
    Mode {
        name: String,
    },
    Input {
        name: String,
    },
    Brightness {
        value: String,
    },
    Contrast {
        value: String,
    },
    Volume {
        value: String,
    },
    Mute {
        state: String,
    },
    Profile {
        #[command(subcommand)]
        action: ProfileCommand,
    },
}
#[derive(Subcommand)]
enum ProfileCommand {
    List,
    Show { name: String },
    Apply { name: String },
    Save { name: String },
}

fn run(cli: &Cli) -> Result<()> {
    let selection = Selection {
        bus: cli.target.selector.bus,
        display: cli.target.selector.display,
        monitor: cli.target.selector.monitor.clone(),
        model: cli.target.model.clone(),
        strict: cli.target.strict,
    };
    let json = cli.json;
    match &cli.command {
        None | Some(Command::Gui) => open_gui(selection),
        Some(Command::List) => print(&displays::discover(Path::new(displays::DRM_ROOT))?, json),
        Some(Command::Status) => print(&connect(&selection)?.status()?, json),
        Some(Command::Codes) => print(&features::features(connect(&selection)?.benq), json),
        Some(Command::Capabilities) => print(&connect(&selection)?.transport.capabilities()?, json),
        Some(Command::Get { features: names }) => {
            let monitor = connect(&selection)?;
            let codes = names
                .iter()
                .map(|name| features::code(monitor.benq, name))
                .collect::<Result<Vec<_>>>()?;
            print(&monitor.readings(&codes)?, json)
        }
        Some(Command::Set { feature, value }) => set(&connect(&selection)?, feature, value),
        Some(Command::Mode { name }) => connect(&selection)?.set_named("picture-mode", name),
        Some(Command::Input { name }) => connect(&selection)?.set_named("input", name),
        Some(Command::Brightness { value }) => connect(&selection)?.set_named("brightness", value),
        Some(Command::Contrast { value }) => connect(&selection)?.set_named("contrast", value),
        Some(Command::Volume { value }) => connect(&selection)?.set_named("volume", value),
        Some(Command::Mute { state }) => connect(&selection)?.set_named("mute", state),
        Some(Command::Profile { action }) => run_profile(action, selection, json),
    }
}
fn run_profile(action: &ProfileCommand, mut selection: Selection, json: bool) -> Result<()> {
    let config = Config::load()?;
    match action {
        ProfileCommand::List => print(&config.profiles, json),
        ProfileCommand::Show { name } => {
            let profile = config.profile(name)?;
            let benq = profile_model_is_benq(selection.model.as_deref(), profile, &config);
            print(&profile.plan(benq)?, json)
        }
        ProfileCommand::Apply { name } => {
            let profile = config.profile(name)?;
            if selection.bus.is_none() && selection.display.is_none() && selection.monitor.is_none()
            {
                selection.monitor = profile.monitor.clone();
            }
            let monitor = connect_with(&selection, &config)?;
            monitor.apply(&profile.plan(monitor.benq)?)
        }
        ProfileCommand::Save { name } => {
            print!("{}", connect_with(&selection, &config)?.save_profile(name)?);
            Ok(())
        }
    }
}
#[cfg(feature = "gui")]
fn open_gui(selection: Selection) -> Result<()> {
    gui::run(selection)
}
#[cfg(not(feature = "gui"))]
fn open_gui(_selection: Selection) -> Result<()> {
    anyhow::bail!("This build has no GUI; rebuild with the gui feature or use a CLI command")
}
/// Connects to the selected monitor, reading the config only when
/// `--monitor` may name an alias in it.
fn connect(selection: &Selection) -> Result<Monitor> {
    let config = if selection.monitor.is_some() {
        Config::load()?
    } else {
        Config::default()
    };
    connect_with(selection, &config)
}
fn connect_with(selection: &Selection, config: &Config) -> Result<Monitor> {
    let connected = displays::discover(Path::new(displays::DRM_ROOT))?;
    Monitor::connect(selection, config, &connected)
}
/// Named continuous and choice features are checked against their bounds and
/// labels. Raw codes and raw-kind features are sent unchecked.
fn set(monitor: &Monitor, feature: &str, value: &str) -> Result<()> {
    if features::feature(monitor.benq, feature).is_ok() {
        return monitor.set_named(feature, value);
    }
    monitor.apply(&[Step {
        code: features::code(monitor.benq, feature)?,
        value: features::number(value)?,
        label: format!("{feature} {value}"),
    }])
}
/// Chooses the feature set for `profile show` without touching sysfs or DDC:
/// `--model`, then the model in the profile's monitor alias, then BenQ RD.
fn profile_model_is_benq(model: Option<&str>, profile: &Profile, config: &Config) -> bool {
    let alias_model = profile
        .monitor
        .as_ref()
        .and_then(|name| config.monitors.get(name))
        .and_then(|alias| alias.model.as_deref());
    model.or(alias_model) != Some("mccs")
}
fn print(value: &impl serde::Serialize, json: bool) -> Result<()> {
    if json {
        println!("{}", serde_json::to_string(value)?);
    } else {
        for line in text_lines(&serde_json::to_value(value)?) {
            println!("{line}");
        }
    }
    Ok(())
}
fn main() {
    let cli = Cli::parse();
    if let Err(error) = run(&cli) {
        if cli.json {
            eprintln!(
                "{}",
                serde_json::json!({"level":"error","message":format!("{error:#}")})
            );
        } else {
            eprintln!("freepilot: {error:#}");
        }
        std::process::exit(1);
    }
}

fn text_lines(value: &serde_json::Value) -> Vec<String> {
    use serde_json::Value;
    match value {
        Value::Array(values) => values.iter().flat_map(text_lines).collect(),
        Value::Object(fields) if fields.contains_key("code") => {
            if let Some(label) = fields.get("label").and_then(Value::as_str) {
                return vec![
                    fields
                        .get("name")
                        .and_then(Value::as_str)
                        .map_or_else(|| label.into(), |name| format!("{name:26} {label}")),
                ];
            }
            let name = fields.get("name").and_then(Value::as_str).unwrap_or("VCP");
            if let Some(description) = fields.get("description").and_then(Value::as_str) {
                return vec![format!(
                    "{name:26} 0x{:02x}  {description}",
                    value["code"].as_u64().unwrap_or_default()
                )];
            }
            let number = value["value"]
                .as_u64()
                .map_or("unreadable".into(), |v| v.to_string());
            let maximum = value["max"]
                .as_u64()
                .map_or(String::new(), |v| format!(" / {v}"));
            vec![format!("{name:26} {number}{maximum}")]
        }
        Value::Object(fields) if fields.contains_key("connector") => vec![format!(
            "{:18} {:8} {} {}  serial {}",
            value["connector"].as_str().unwrap_or("?"),
            value["bus"]
                .as_u64()
                .map_or("-".into(), |bus| format!("i2c-{bus}")),
            value["manufacturer"].as_str().unwrap_or(""),
            value["model"].as_str().unwrap_or(""),
            value["serial"].as_str().unwrap_or("")
        )],
        Value::Object(fields) => fields
            .iter()
            .flat_map(|(key, value)| {
                let lines = text_lines(value);
                if value.get("code").is_some() {
                    lines
                } else {
                    let mut result = vec![format!("{key}:")];
                    result.extend(lines.into_iter().map(|line| format!("  {line}")));
                    result
                }
            })
            .collect(),
        Value::String(text) => vec![text.clone()],
        _ => vec![value.to_string()],
    }
}
