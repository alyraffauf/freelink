# freelink

Control BenQ RD series monitors from Linux over DDC/CI, without Display Pilot 2.

freelink needs Python 3.12 and `ddcutil`, and has no other runtime
dependencies. It has not been tested on a monitor yet. See
[NOTES.md](NOTES.md) for where the VCP map comes from and what to check first.

## Usage

```sh
uv run freelink status
uv run freelink mode coding-dark
uv run freelink input usb-c
uv run freelink brightness 40
uv run freelink get eco-privacy kvm
uv run freelink codes
```

Pick a monitor with `--display N` or `--bus N`. You need read-write access to
`/dev/i2c-*`. On NixOS, set `hardware.i2c.enable = true` and add your user to
the `i2c` group.

## Development

```sh
uv sync
uv run ruff format --check
uv run ruff check
uv run ty check
uv run pytest
```
