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
```

You need read-write access to `/dev/i2c-*`. On NixOS, set
`hardware.i2c.enable = true` and add your user to the `i2c` group.

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

[monitors.tv]
connector = "HDMI-A-1"
```

### JSON

Add `--json`, before or after the command, to make `status`, `get`, `codes`,
and `list` print one line of JSON. Write commands print nothing either way.
The format may still change before v0.1.0.

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
