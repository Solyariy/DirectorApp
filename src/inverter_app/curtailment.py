"""
Tell curtailed solar readings from ones that show the available PV power.

A reading is unconstrained when the battery still absorbs surplus (charging
below its limit and not full) or when a PV string sits at its usual MPP
voltage. When nothing absorbs the surplus, the MPPT moves the strings away
from MPP (on Deye: toward Voc), so a voltage clearly above the string's
reference MPP voltage marks a curtailed reading.
"""

from collections.abc import Iterable
from enum import StrEnum
from statistics import median

from src.inverter_app.schemas import EnergySnapshotSchema

DARK_SOLAR_W = 50
FULL_BATTERY_PCT = 95
CHARGE_HEADROOM_RATIO = 0.9
CURTAILED_VOLTAGE_RATIO = 1.08
# A string must produce at least this much to give a usable MPP voltage
# sample (low light shifts Vmp down).
MPP_SAMPLE_MIN_POWER_W = 200

PV_STRINGS = {
    "pv1": ("pv1_voltage_v", "pv1_power_w"),
    "pv2": ("pv2_voltage_v", "pv2_power_w"),
}


class PvState(StrEnum):
    DARK = "dark"
    UNCONSTRAINED = "unconstrained"
    CURTAILED = "curtailed"
    UNKNOWN = "unknown"


def battery_charge_current_a(snapshot: EnergySnapshotSchema) -> float:
    if snapshot.battery_voltage_v <= 0:
        return 0.0
    return max(-snapshot.battery_power_w, 0) / snapshot.battery_voltage_v


def has_battery_headroom(snapshot: EnergySnapshotSchema) -> bool | None:
    """True when the battery can take more charge; None if unknown."""
    limit = snapshot.battery_max_charge_current_a
    if limit is None:
        return None
    if snapshot.battery_charge_pct >= FULL_BATTERY_PCT:
        return False
    charge = battery_charge_current_a(snapshot)
    return charge < limit * CHARGE_HEADROOM_RATIO


def _active_strings(snapshot: EnergySnapshotSchema):
    for name, (voltage_field, power_field) in PV_STRINGS.items():
        voltage = getattr(snapshot, voltage_field)
        power = getattr(snapshot, power_field)
        if voltage is not None and power is not None and power > 0:
            yield name, voltage, power


def voltage_ratios(
    snapshot: EnergySnapshotSchema,
    mpp_voltages: dict[str, float],
) -> dict[str, float]:
    """Operating voltage / reference MPP voltage per producing string."""
    return {
        name: voltage / mpp_voltages[name]
        for name, voltage, _ in _active_strings(snapshot)
        if mpp_voltages.get(name)
    }


def classify(
    snapshot: EnergySnapshotSchema,
    mpp_voltages: dict[str, float] | None = None,
) -> PvState:
    if snapshot.solar_power_w < DARK_SOLAR_W:
        return PvState.DARK
    if has_battery_headroom(snapshot):
        return PvState.UNCONSTRAINED
    ratios = voltage_ratios(snapshot, mpp_voltages or {})
    if not ratios:
        return PvState.UNKNOWN
    if any(r > CURTAILED_VOLTAGE_RATIO for r in ratios.values()):
        return PvState.CURTAILED
    # Battery can't absorb more, but strings sit at MPP: the load takes all
    # the panels can give, so solar power is the available power.
    return PvState.UNCONSTRAINED


def estimate_mpp_voltages(
    snapshots: Iterable[EnergySnapshotSchema],
) -> dict[str, float]:
    """
    Reference MPP voltage per string: median operating voltage over
    readings taken while the battery had headroom (the MPPT then tracks
    the true maximum power point).
    """
    samples: dict[str, list[float]] = {name: [] for name in PV_STRINGS}
    for snapshot in snapshots:
        if not has_battery_headroom(snapshot):
            continue
        for name, voltage, power in _active_strings(snapshot):
            if power >= MPP_SAMPLE_MIN_POWER_W:
                samples[name].append(voltage)
    return {name: median(v) for name, v in samples.items() if v}
