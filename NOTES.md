# freepilot notes

freepilot drives BenQ RD series monitors through `ddcutil`. The VCP map
comes from Display Pilot 2 for Linux 1.1.4.0. None of it has been tried on a
monitor yet.

## Where the map comes from

- **Standard codes** come from `libMonitor.so`: brightness `0x10`, volume
  `0x62`, mute `0x8D`, picture mode `0xDC`, firmware `0xC9`, OSD status `0xCA`,
  picture blank `0xF6`.
- **Picture mode values** come from the per-model `RDxxxx.xml` resources in
  `libRDPackage`. The app writes `(SHCode << 8) | Code` to `0xDC`. Every RD
  model uses `SHCode="0x00"`.
- **Input source values** for `0x60` come from the plugin's `inputSourceMap`.
  BenQ uses `0x13` for USB-C, where MCCS suggests `0x1B`.
- **BenQ-specific codes** (`0xD0`-`0xFD` and others) come from the constant
  passed to each `setVCP`/`getVCP` call in the plugin's feature classes, such as
  `DpEcoPrivacy` and `DpKvmSwitch`. The code is reliable. Its values are not.
- **Write delays** come from `RD_vcpDelay.xml`.

## First checks on hardware

1. `ddcutil detect`, then `ddcutil capabilities`. Compare the listed codes with
   `freepilot codes`.
2. `freepilot status`, then change each setting on the OSD and rerun it.
3. `freepilot mode coding-dark` and `freepilot input usb-c`. Confirm the
   picture-mode and input values.
4. For each unconfirmed feature, read it with `freepilot get <name>`, change it
   on the OSD, and read it again to learn its values.

## Open questions

- **Monitor shortcut buttons.** `DpShortcuts` handles keyboard shortcuts on the
  computer and never polls the monitor. The monitor's own buttons may send key
  events over USB. Check `libinput debug-events` while pressing them.
- **USB-C2 and Thunderbolt values** on models that have those ports.
