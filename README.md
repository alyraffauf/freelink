# freepilot

Control BenQ RD series monitors from Linux over DDC/CI, without Display Pilot 2.

freepilot needs Python 3.12 and `ddcutil`, and has no other runtime
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

Pick a monitor with `--display N` or `--bus N`. You need read-write access to
`/dev/i2c-*`. On NixOS, set `hardware.i2c.enable = true` and add your user to
the `i2c` group.

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
