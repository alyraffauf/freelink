"""Turn readings and feature lists into text lines and JSON data."""

from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from freepilot.features import FEATURES, Feature, feature_name, name_for
lazy from freepilot.displays import Display
lazy from freepilot.vcp import Reading

type JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class Output:
    """What a read command shows: lines for people, data for --json."""

    lines: list[str]
    data: object


def feature_for(code: int) -> Feature | None:
    """Return the feature for a VCP code, if freepilot knows it."""
    name = feature_name(code)
    return FEATURES[name] if name else None


def format_reading(reading: Reading | None) -> str:
    """Show a reading the way its feature's kind calls for.

    Codes freepilot does not know show as the transport reported them:
    current/max when it gave a maximum, otherwise hex.
    """
    if reading is None or reading.value is None:
        return "unreadable"
    match feature_for(reading.code):
        case Feature(kind="choice", values=values):
            return name_for(values, reading.value) or f"0x{reading.value:02x}"
        case Feature(kind="continuous") | None if reading.maximum is not None:
            return f"{reading.value}/{reading.maximum}"
        case Feature(kind="continuous"):
            return str(reading.value)
        case _:
            return f"0x{reading.value:02x}"


def reading_json(code: int, reading: Reading | None) -> JsonObject:
    """Describe one reading. value is null when the monitor did not answer.

    label names a known choice value. max appears for continuous features,
    and for unknown codes when the transport reported one.
    """
    feature = feature_for(code)
    value = reading.value if reading else None
    data: JsonObject = {
        "code": code,
        "name": feature_name(code),
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


def status_output(status: Mapping[str, Reading | None]) -> Output:
    """Show the status features, one per line or keyed by name."""
    return Output(
        lines=[
            f"{name:<14} {format_reading(reading)}" for name, reading in status.items()
        ],
        data={
            name: reading_json(FEATURES[name].code, reading)
            for name, reading in status.items()
        },
    )


def readings_output(codes: Sequence[int], readings: Mapping[int, Reading]) -> Output:
    """Show requested readings in the order asked for, repeats included."""
    lines = []
    for code in codes:
        label = feature_name(code) or f"0x{code:02x}"
        lines.append(f"{label:<24} {format_reading(readings.get(code))}")
    return Output(
        lines=lines, data=[reading_json(code, readings.get(code)) for code in codes]
    )


def codes_output() -> Output:
    """List every VCP code freepilot knows about, in code order."""
    features = sorted(FEATURES.items(), key=lambda item: item[1].code)
    lines = []
    for name, feature in features:
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
        for name, feature in features
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
