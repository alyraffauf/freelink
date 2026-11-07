use std::{
    fs,
    os::unix::fs::PermissionsExt,
    process::{Command, Output},
};
struct Fixture {
    directory: tempfile::TempDir,
}
impl Fixture {
    fn new(config: &str) -> Self {
        let directory = tempfile::tempdir().unwrap();
        fs::write(directory.path().join("config.toml"), config).unwrap();
        let script = directory.path().join("ddcutil");
        let shell = std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|path| path.join("sh"))
            .find(|path| path.is_file())
            .expect("Tests need a POSIX shell");
        let fake_ddcutil = format!(
            r#"#!{shell}
printf '%s\n' "$*" >> "$LOG"
shift 2
case "$1" in
    capabilities) echo 'Unparsed capabilities string: (vcp(10))';;
    getvcp)
        echo 'VCP 10 C 40 100'
        if [ -n "$PARTIAL_GETVCP" ]; then
            echo 'VCP 62 ERR'
            exit 1
        fi;;
    setvcp)
        if [ "$2" = 0x12 ]; then
            echo 'write failed' >&2
            exit 1
        fi;;
    *) exit 2;;
esac
"#,
            shell = shell.display(),
        );
        fs::write(&script, fake_ddcutil).unwrap();
        fs::set_permissions(script, fs::Permissions::from_mode(0o755)).unwrap();
        Self { directory }
    }
    fn run(&self, args: &[&str]) -> Output {
        self.command()
            .args(["--bus", "999", "--model", "benq-rd"])
            .args(args)
            .output()
            .unwrap()
    }
    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_freepilot"));
        command
            .env("PATH", self.directory.path())
            .env(
                "FREEPILOT_CONFIG",
                self.directory.path().join("config.toml"),
            )
            .env("LOG", self.directory.path().join("log"))
            .env_remove("PARTIAL_GETVCP");
        command
    }
    fn log(&self) -> String {
        fs::read_to_string(self.directory.path().join("log")).unwrap_or_default()
    }
}
#[test]
fn cli_outputs_json_and_passes_the_selected_bus() {
    let fixture = Fixture::new("");
    let output = fixture.run(&["get", "brightness", "--json"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(data[0]["value"], 40);
    assert!(fixture.log().contains("--bus 999 getvcp --terse 0x10"));
}
#[test]
fn strict_profile_checks_all_steps_before_any_write() {
    let fixture = Fixture::new("[profiles.desk]\nbrightness=40\ncontrast=50\n");
    let output = fixture.run(&["--strict", "profile", "apply", "desk"]);
    assert!(!output.status.success());
    assert!(fixture.log().contains("capabilities"));
    assert!(!fixture.log().contains("setvcp"));
}
#[test]
fn failed_profile_stops_without_retrying_or_writing_later_settings() {
    let fixture = Fixture::new("[profiles.desk]\nbrightness=40\ncontrast=50\nvolume=30\n");
    let output = fixture.run(&["profile", "apply", "desk"]);
    assert!(!output.status.success());
    let log = fixture.log();
    assert_eq!(log.lines().count(), 2);
    assert!(log.contains("setvcp 0x10 40"));
    assert!(log.contains("setvcp 0x12 50"));
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(error.contains("sent:"));
    assert!(error.contains("not attempted:"));
}
#[test]
fn invalid_profile_never_starts_ddcutil() {
    let fixture = Fixture::new("[profiles.desk]\nbrightness=40\ninput='misspelled'\n");
    assert!(!fixture.run(&["profile", "apply", "desk"]).status.success());
    assert!(fixture.log().is_empty());
}
#[test]
fn set_checks_named_features_and_sends_raw_codes_unchecked() {
    let fixture = Fixture::new("");
    assert!(
        fixture
            .run(&["set", "night-protection", "auto"])
            .status
            .success()
    );
    assert!(fixture.log().contains("setvcp 0xd1 2"));
    assert!(fixture.run(&["set", "0x87", "7"]).status.success());
    assert!(fixture.log().contains("setvcp 0x87 7"));
    let rejected = Fixture::new("");
    let output = rejected.run(&["set", "low-blue-light", "50"]);
    assert!(!output.status.success());
    assert!(!rejected.log().contains("setvcp"));
}
#[test]
fn status_reports_unreadable_codes_when_ddcutil_fails_on_some() {
    let fixture = Fixture::new("");
    let output = fixture
        .command()
        .args(["--bus", "999", "--model", "mccs", "status", "--json"])
        .env("PARTIAL_GETVCP", "1")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let status: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(status["brightness"]["value"], 40);
    assert!(status["volume"]["value"].is_null());
}
#[test]
fn profile_show_uses_the_model_of_the_profile_monitor_alias() {
    let fixture = Fixture::new(
        "[monitors.tv]\nconnector = 'HDMI-A-1'\nmodel = 'mccs'\n\
         [profiles.couch]\nmonitor = 'tv'\ninput = 'displayport2'\n",
    );
    let output = fixture
        .command()
        .args(["profile", "show", "couch", "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let steps: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(steps[0]["code"], 0x60);
    assert_eq!(steps[0]["value"], 16);
    assert!(fixture.log().is_empty());
}
