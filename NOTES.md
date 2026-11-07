# Monitor protocol notes

The VCP map in [src/features.rs](src/features.rs) comes from Display Pilot 2
for Linux 1.1.4.0. Its AppImage resources and symbols were inspected without
executing it. Freepilot includes no vendor code or assets.

## Mapping provenance

Standard codes come from `libMonitor.so`. BenQ codes and values come from
`libRDPackage`, its per-model `RDxxxx.xml` resources, and QML controls.
Write delays come from `RD_vcpDelay.xml`. Features without a verified value
mapping remain raw.

| Control             | VCP                    | Verified values or source                                                     |
| ------------------- | ---------------------- | ----------------------------------------------------------------------------- |
| Picture mode        | `0xDC`                 | Per-model XML, encoded as `(SHCode << 8) \| Code`; RD models use `SHCode = 0` |
| Input               | `0x60`                 | `inputSourceMap`; BenQ USB-C is `0x13`                                        |
| Color temperature   | `0x14`                 | 5000 K = 4, 6500 K = 5, 9300 K = 8, User = 11                                 |
| RGB gain            | `0x16`, `0x18`, `0x1A` | Maximum 100 reported by the checked RD280UG                                   |
| Low blue light      | `0x19`                 | QML range 0 to 5                                                              |
| Gamma               | `0x72`                 | 1.6 = 60, 1.8 = 80, 2.0 = 100, sRGB = 119, 2.2 = 120, 2.4 = 140, 2.6 = 160    |
| Bright Intelligence | `0x81`                 | `DpBIPlus`: Off = 0, B.I.+ = 1, B.I. = 2                                      |
| Sharpness           | `0x87`                 | Maximum 10 reported by the checked RD280UG                                    |
| Night level         | `0xD0`                 | QML range 1 to 10                                                             |
| Night protection    | `0xD1`                 | `DpNightProtection`: Off = 0, On = 1, Auto = 2                                |
| KVM                 | `0xE4`                 | `DpKvmSwitch`: Thunderbolt = 1, USB-B = 2, USB-C = 3, Auto = 4                |

The checked RD280UG advertises only USB-B, USB-C, and Auto for KVM. The GUI
filters presets and switch targets using the monitor's capabilities. Extra
controls are read in a batch; unreadable settings preserve the other values.
Some picture modes lock settings even when their codes are advertised.

## DisplayPort bus discovery

On the checked AMDGPU system, the connector's `ddc` link points to a hardware
bus that does not answer DDC. Its `i2c-*` child is the working AUX bus,
confirmed by `ddcutil detect --verbose`. Discovery prefers that child for
DisplayPort connectors and the `ddc` link for other connectors.

## Hardware validation limits

Read access has been checked on a BenQ RD280UG over DisplayPort. Automated
tests and isolated GUI checks use a fake DDC monitor. Physical writes still
need validation, including input and KVM switches that may disconnect the
host before a read-back completes.

By default, ddcutil verifies `setvcp` immediately for features such as picture
mode and KVM. Freepilot's vendor delay starts after ddcutil returns. A monitor
that is still switching may report the old value and trigger a verification
failure. Whether the RD280UG needs delayed verification remains untested.
