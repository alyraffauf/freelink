# freelink

Control BenQ RD series monitors from Linux over DDC/CI, without Display Pilot 2.

`freelink.py` is a single Python script with no dependencies beyond `ddcutil`.
It has not been tested on a monitor yet. See [NOTES.md](NOTES.md) for where
the VCP map comes from and what to check first.

## Usage

```sh
python3 freelink.py status
python3 freelink.py mode coding-dark
python3 freelink.py input usb-c
python3 freelink.py brightness 40
python3 freelink.py get eco-privacy kvm
python3 freelink.py codes
```

Pick a monitor with `--display N` or `--bus N`. You need read-write access to
`/dev/i2c-*`. On NixOS, set `hardware.i2c.enable = true` and add your user to
the `i2c` group.
