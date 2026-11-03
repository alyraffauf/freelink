# freepilot

Control BenQ RD series monitors from Linux over DDC/CI, without Display Pilot 2.

freepilot needs Python 3.15 and `ddcutil`, and has no other runtime
dependencies. It has not been tested on a monitor yet. See
[NOTES.md](NOTES.md) for where the VCP map comes from and what to check first.

## Usage

```sh
uv run freepilot status
uv run freepilot mode coding-dark
uv run freepilot input usb-c
uv run freepilot brightness 40
uv run freepilot get eco-privacy kvm
uv run freepilot codes
uv run freepilot capabilities
```

You need read-write access to `/dev/i2c-*`. On NixOS, set
`hardware.i2c.enable = true` and add your user to the `i2c` group.

### BenQ RD and other monitors

freepilot reads each monitor's EDID to decide which names to use:

- A BenQ monitor (`BNQ`) with a model name starting with `RD` gets the full
  BenQ RD set, including picture modes and BenQ's input values. USB-C is
  `0x13`.
- Any other monitor gets standard MCCS controls only: brightness, contrast,
  input, volume, sharpness, and mute. BenQ names such as `usb-c` and picture
  modes are refused.

`freepilot codes` shows which set applies. If a monitor is misidentified, or
selected with `--display` so freepilot can't read its EDID, pass
`--model benq-rd` or `--model mccs`, or set `model` in its config alias.
`get` and `set` accept raw codes on any monitor.

### Capabilities

`freepilot capabilities` shows the codes and values the monitor says it
supports, beside freepilot's names for them. The last line lists features
freepilot knows that the monitor doesn't list.

Monitors often leave supported codes out, so freepilot sends writes
whatever the list says. Add `--strict` to refuse writes it doesn't list.
This fetches the capability string first, which takes about a second.

### Pick a monitor

`freepilot list` shows connected monitors, read from sysfs. It needs no
i2c access.

```console
$ freepilot list
card1-DP-1         i2c-4    BNQ BenQ RD280U  serial ABC123
```

Pass `--monitor` with any of these, checked in this order:

1. A config alias.
2. The serial.
3. The connector name: `card1-DP-1`, or `DP-1`.
4. Part of the model name.

The first rule that matches anything decides. If it matches several
monitors, freepilot stops and lists them. `--bus N` and `--display N` still
work. Without any of them, ddcutil picks its default display.

Aliases live in `$XDG_CONFIG_HOME/freepilot/config.toml`. Set
`$FREEPILOT_CONFIG` to use another file.

```toml
[monitors.desk]
serial = "ABC123"
model = "benq-rd" # optional, see above

[monitors.tv]
connector = "HDMI-A-1"
```

### Profiles

Profiles apply several settings at once. Add them to `config.toml`:

```toml
[profiles.coding]
monitor = "desk" # optional; --monitor, --bus, or --display override it
picture-mode = "coding-dark"
brightness = 40
contrast = 50

[profiles.coding.vcp] # raw codes, as hex strings
"0xd1" = 2
```

```sh
freepilot profile list
freepilot profile show coding
freepilot profile apply coding
freepilot profile save evening >> ~/.config/freepilot/config.toml
```

The named keys are `picture-mode`, `input`, `brightness`, `contrast`,
`sharpness`, `volume`, and `mute`. `apply` writes picture mode first,
because changing it resets levels on most monitors. Then come levels, mute,
and raw codes in ascending order. Input goes last, because it may switch the
monitor away from this machine.

freepilot checks the whole profile before writing anything. Raw codes can't
set picture mode, input, power, KVM, or the reset codes. Use the named keys
for picture mode and input. If a write fails, freepilot stops and lists what
was sent and what was never tried. The monitor doesn't confirm writes, and
nothing is rolled back.

`save` prints the current settings as a profile table. Unreadable values
become comments, and so does input, so applying a saved profile doesn't
switch inputs unless you uncomment it.

### Talk to the bus directly

`--transport i2c` skips ddcutil and speaks DDC/CI on `/dev/i2c-N` itself.
It takes the same bus lock as ddcutil, retries busy replies, and never
resends a write that failed. It hasn't been tried on a monitor yet, so
ddcutil stays the default. Without `--bus` or `--monitor`, it uses the only
connected monitor. `--display` only works with ddcutil.

### JSON

Add `--json`, before or after the command, to make `status`, `get`, `codes`,
`list`, `capabilities`, `profile list`, and `profile show` print one line of
JSON. Write commands print nothing either way, and `profile save` always
prints TOML. The format may still change before v0.1.0.

Each reading looks like this:

```json
{ "code": 96, "name": "input", "kind": "choice", "value": 19, "label": "usb-c" }
```

- `kind` is `continuous`, `choice`, `raw`, or `unknown` for codes freepilot
  doesn't know.
- `value` is `null` when the monitor didn't answer.
- `label` names a known choice value.
- `max` appears for continuous features, and for unknown codes when ddcutil
  reported one.

`status` prints an object keyed by feature name. `get` prints a list in the
order you asked. `codes` lists each feature with its kind and value names.
Errors go to stderr as `{"level": "error", "message": "..."}`, with exit
status 1.

```sh
freepilot --json status | jq -r '.brightness.value'
```

## Nix

Run it from the flake:

```sh
nix run github:alyraffauf/freepilot -- status
```

Or add the flake input and install `packages.${system}.freepilot`. The package
wraps `ddcutil` onto `PATH`. It builds for `x86_64-linux` and `aarch64-linux`.

### NixOS

The NixOS module installs freepilot and turns on `hardware.i2c`. That loads
`i2c-dev` and gives `/dev/i2c-*` to the `i2c` group and to users at the
local seat. Add yourself to the group to use freepilot over SSH or from
services:

```nix
{config, inputs, ...}: {
  imports = [inputs.freepilot.nixosModules.default];
  programs.freepilot.enable = true;
  users.users.<name>.extraGroups = [config.hardware.i2c.group];
}
```

Log out and back in after changing groups.

### Home Manager

The Home Manager module installs freepilot and writes `config.toml` from
`settings`:

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

You still need i2c access from the NixOS side.

## Development

`nix develop` provides Python, uv, and `ddcutil`. `nix flake check` runs
formatting, `ty`, and the tests.

```sh
uv sync
uv run ruff format --check
uv run ruff check
uv run ty check
uv run pytest
```
