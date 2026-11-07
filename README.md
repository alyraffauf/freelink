# Freepilot

Control BenQ RD monitors on Linux with a GPUI desktop app and a command line
interface. Freepilot uses `ddcutil` to communicate over DDC/CI. Other monitors
get standard MCCS controls, including brightness, contrast, volume, and input.

## Run Freepilot

Open the desktop app from the Nix flake:

```sh
nix run github:alyraffauf/freepilot
```

Or install `packages.${system}.freepilot` from the flake and run `freepilot`.
The flake provides packages for `x86_64-linux` and `aarch64-linux`, with
`ddcutil` included on `PATH`.

Your user needs read-write access to `/dev/i2c-*`. For NixOS permissions and
Home Manager configuration, see [Configure NixOS](#configure-nixos) and
[Configure Home Manager](#configure-home-manager).

## Use the desktop app

Adjust brightness, contrast, sharpness, and volume with the sliders. On BenQ
RD monitors, choose picture modes, adjust eye comfort settings, or expand
**Advanced color** for color temperature, gamma, and RGB gains. Controls use
the monitor's advertised capabilities and reported ranges. Unreadable
controls are disabled. If several displays are connected, use the display
picker at the top.

Drag a slider to preview its value, then release to apply it. Use Tab to
focus controls and Enter or Space to activate buttons. On a focused slider,
use arrow keys for one step, Shift with arrow keys for larger steps, Home
or End for the endpoints, and Escape to cancel an adjustment. Press `r`
to refresh.

Input and KVM buttons ask for confirmation before switching. KVM routes
the monitor's USB devices and may disconnect your keyboard and mouse from
this computer. Failures appear in a dismissible overlay. If a setting was
sent but could not be read back, the message says so.

To switch picture modes from the tray, use a desktop panel with a
StatusNotifier host, such as Waybar's `tray` module. Choose **Picture mode**
from the tray menu. Click the icon or choose **Open Freepilot** to focus
the window. Closing the window or choosing **Quit** exits the app.

## Use the CLI

Pass a subcommand to run without a window:

```sh
freepilot list
freepilot status
freepilot brightness 40
freepilot mode coding-dark
freepilot input usb-c
freepilot set low-blue-light 3
freepilot set night-protection auto
freepilot set gamma 2.2
```

Run `freepilot codes` to list known features and their value names.
Use `freepilot get brightness contrast` to read specific settings, or
`freepilot capabilities` to inspect what the monitor advertises.
For command options, run `freepilot --help` or `freepilot <subcommand> --help`.

Freepilot identifies BenQ RD monitors from their EDID. To override detection,
pass `--model benq-rd` or `--model mccs`. Named settings use the selected
model's values and range checks. Numeric VCP codes and features listed as
`raw` accept any 16-bit value:

```sh
freepilot get 0x19
freepilot set 0x19 3
```

Add `--strict` to check writes against the capability list and refuse levels
above the monitor's reported maximum. Without it, Freepilot allows writes
to codes omitted from the capability list. The GUI shows only the current
input or KVM target when the monitor provides no list of choices.

### Select a monitor

Run `freepilot list` to find connector names, serials, and I²C buses.
Select a monitor explicitly with `--monitor`, `--bus`, or `--display`:

```sh
freepilot --monitor DP-1 status
freepilot --bus 9 brightness 40
```

`--monitor` matches a config alias first, then a serial, full connector name,
short connector name, or part of the model name. Model matches ignore case.
An ambiguous match fails instead of choosing a display. An alias must match
its configured serial or connector.

To define aliases, create `~/.config/freepilot/config.toml`:

```toml
[monitors.desk]
serial = "ABC123"
model = "benq-rd" # optional detection override

[monitors.tv]
connector = "HDMI-A-1"
```

If you set `XDG_CONFIG_HOME` to an absolute path, the config file lives at
`$XDG_CONFIG_HOME/freepilot/config.toml`. Set `FREEPILOT_CONFIG` to select
another file. If the config has an error, the GUI reports it and keeps the
last valid config for monitor controls. Fix the file to use profiles again.

### Apply profiles

Add profiles to the same config file:

```toml
[profiles.coding]
monitor = "desk"
picture-mode = "coding-dark"
brightness = 40
contrast = 50

[profiles.coding.vcp]
"0xd1" = 2 # Night protection: Auto
```

Inspect or apply a profile with the CLI:

```sh
freepilot profile list
freepilot profile show coding
freepilot profile apply coding
freepilot profile save evening
```

`save` prints a TOML profile to copy into your config. It comments out input
and unreadable values. `show` prints the planned writes without accessing
the monitor. To choose its value table, pass `--model`, set the profile's
monitor alias model, or use the BenQ RD default.

The named profile keys are `picture-mode`, `brightness`, `contrast`,
`sharpness`, `volume`, `mute`, and `input`. Other settings use the `vcp`
table. Profiles write picture mode first, then levels, mute, raw codes in
ascending order, and input last. Reset, power, KVM, and settings store and restore
commands are forbidden as raw profile codes. Use named keys for picture
mode and input.

The CLI uses the profile's `monitor` unless you pass a selector. The GUI's
profile buttons apply to the currently selected monitor, including any
configured input change. Freepilot validates every setting before the first
write. If a write fails, it stops and reports which steps were sent and which
were skipped. It does not retry or roll back writes.

### Read JSON output

Add `--json` to read commands for one line of JSON:

```sh
freepilot --json status | jq -r '.brightness.value'
freepilot --json get input
```

`status` returns an object keyed by feature name. `get` returns a list in the
requested order. Each reading has `code`, `name`, `kind`, `value`, `max`,
and `label` fields. Unreadable values and unknown labels are `null`.
Partial read failures preserve the other readings.

Write commands print nothing. `profile save` always prints TOML. With
`--json`, runtime errors print `{"level":"error","message":"..."}` to stderr
and exit with status 1. Invalid arguments print usage text and exit with
status 2.

## Configure NixOS

Import the NixOS module to install Freepilot and enable I²C support.
Add your user to the I²C group for access over SSH or from services:

```nix
{config, inputs, ...}: {
	imports = [inputs.freepilot.nixosModules.default];
	programs.freepilot.enable = true;
	users.users.<name>.extraGroups = [config.hardware.i2c.group];
}
```

Log out and back in after changing groups.

## Configure Home Manager

Import the Home Manager module to install Freepilot and generate
`config.toml`. I²C permissions still need system configuration.

```nix
{inputs, ...}: {
	imports = [inputs.freepilot.homeModules.default];
	programs.freepilot = {
		enable = true;
		settings = {
			monitors.desk.serial = "ABC123";
			profiles.coding = {
				monitor = "desk";
				picture-mode = "coding-dark";
				brightness = 40;
			};
		};
	};
}
```

## Develop

Enter `nix develop` for Rust, Cargo, ddcutil, and GPUI's native dependencies.
Run the app or checks from that shell:

```sh
cargo run
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
cargo test --locked --no-default-features
nix flake check
```

For a CLI-only build, run `cargo build --no-default-features`.
Tests use synthetic EDID data and a fake ddcutil executable. See the
[monitor protocol notes](NOTES.md) for mapping provenance, known hardware
behavior, and validation limits.
