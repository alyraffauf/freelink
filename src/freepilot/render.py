"""Turn readings and feature lists into text lines and JSON data."""

from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from freepilot.features import Feature, FeatureSet, name_for
lazy from freepilot.capabilities import Capabilities
lazy from freepilot.displays import Display
lazy from freepilot.vcp import Reading

type JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class Output:
    """What a read command shows: lines for people, data for --json."""

    lines: list[str]
    data: object


def format_reading(reading: Reading | None, features: FeatureSet) -> str:
    """Show a reading the way its feature's kind calls for.

    Codes freepilot does not know show as the transport reported them:
    current/max when it gave a maximum, otherwise hex.
    """
    if reading is None or reading.value is None:
        return "unreadable"
    match features.feature_for(reading.code):
        case Feature(kind="choice", values=values):
            return name_for(values, reading.value) or f"0x{reading.value:02x}"
        case Feature(kind="continuous") | None if reading.maximum is not None:
            return f"{reading.value}/{reading.maximum}"
        case Feature(kind="continuous"):
            return str(reading.value)
        case _:
            return f"0x{reading.value:02x}"


def reading_json(
    code: int, reading: Reading | None, features: FeatureSet
) -> JsonObject:
    """Describe one reading. value is null when the monitor did not answer.

    label names a known choice value. max appears for continuous features,
    and for unknown codes when the transport reported one.
    """
    feature = features.feature_for(code)
    value = reading.value if reading else None
    data: JsonObject = {
        "code": code,
        "name": features.feature_name(code),
        "kind": feature.kind if feature else "unknown",
        "value": value,
    }
    if value is None or reading is None:
        return data
    match feature:
        case Feature(kind="choice", values=values) if label := name_for(values, value):
            data["label"] = label
        case Feature(kind="continuous") | None if reading.maximum is not None:
            data["max"] = reading.maximum
    return data


def status_output(status: Mapping[str, Reading | None], features: FeatureSet) -> Output:
    """Show the status features, one per line or keyed by name."""
    return Output(
        lines=[
            f"{name:<14} {format_reading(reading, features)}"
            for name, reading in status.items()
        ],
        data={
            name: reading_json(features.features[name].code, reading, features)
            for name, reading in status.items()
        },
    )


def readings_output(
    codes: Sequence[int], readings: Mapping[int, Reading], features: FeatureSet
) -> Output:
    """Show requested readings in the order asked for, repeats included."""
    lines = []
    for code in codes:
        label = features.feature_name(code) or f"0x{code:02x}"
        lines.append(f"{label:<24} {format_reading(readings.get(code), features)}")
    return Output(
        lines=lines,
        data=[reading_json(code, readings.get(code), features) for code in codes],
    )


def codes_output(features: FeatureSet) -> Output:
    """List a feature set's VCP codes in code order, under the set's name."""
    ordered = sorted(features.features.items(), key=lambda item: item[1].code)
    lines = [f"{features.description} ({features.name})"]
    for name, feature in ordered:
        marker = "" if feature.values_confirmed else "  (values unconfirmed)"
        lines.append(f"0x{feature.code:02x}  {name:<24} {feature.description}{marker}")
    data = [
        {
            "code": feature.code,
            "name": name,
            "description": feature.description,
            "kind": feature.kind,
            "values": dict(feature.values),
            "values_confirmed": feature.values_confirmed,
        }
        for name, feature in ordered
    ]
    return Output(lines=lines, data=data)


def displays_output(displays: Sequence[Display]) -> Output:
    """List connected monitors with their bus and identity."""
    lines = []
    data = []
    for display in displays:
        edid = display.edid
        bus = f"i2c-{display.bus}" if display.bus is not None else "no bus"
        model = edid.model if edid and edid.model else "unknown model"
        serial = (edid.serial or edid.serial_number) if edid else None
        maker = edid.manufacturer if edid else "???"
        lines.append(
            f"{display.connector:<18} {bus:<8} {maker} {model}"
            + (f"  serial {serial}" if serial else "")
        )
        data.append(
            {
                "connector": display.connector,
                "bus": display.bus,
                "buses": list(display.buses),
                "manufacturer": edid.manufacturer if edid else None,
                "product": edid.product if edid else None,
                "model": edid.model if edid else None,
                "serial": edid.serial if edid else None,
                "serial_number": edid.serial_number if edid else None,
            }
        )
    return Output(lines=lines or ["no connected monitors found"], data=data)


def capabilities_output(capabilities: Capabilities, features: FeatureSet) -> Output:
    """Show what the monitor lists, beside freepilot's names for it.

    The last line lists features freepilot knows that the monitor doesn't,
    which is the first thing to check on new hardware.
    """
    lines = [
        f"{'model':<14} {capabilities.model or 'unknown'}",
        f"{'type':<14} {capabilities.display_type or 'unknown'}",
        f"{'mccs':<14} {capabilities.mccs_version or 'unknown'}",
    ]
    entries = []
    for code, entry in sorted(capabilities.vcp.items()):
        name = features.feature_name(code)
        table = features.values(name) if name else frozendict()
        if entry.malformed:
            shown = "values unreadable"
        else:
            shown = ", ".join(
                " ".join(filter(None, (f"0x{value:02x}", name_for(table, value))))
                for value in entry.values or ()
            )
        lines.append(f"0x{code:02x}  {name or '-':<24} {shown}".rstrip())
        entries.append(
            {
                "code": code,
                "name": name,
                "values": list(entry.values) if entry.values is not None else None,
                "malformed": entry.malformed,
            }
        )
    unlisted = [
        name
        for name, feature in features.features.items()
        if feature.code not in capabilities.vcp
    ]
    if unlisted:
        lines.append(f"not listed by the monitor: {', '.join(unlisted)}")
    return Output(
        lines=lines,
        data={
            "model": capabilities.model,
            "type": capabilities.display_type,
            "mccs_version": capabilities.mccs_version,
            "commands": list(capabilities.commands),
            "vcp": entries,
            "unlisted": unlisted,
            "raw": capabilities.raw,
        },
    )
