"""
Shared loaders for the analysis notebooks: inverter snapshots, Open-Meteo
satellite irradiance, and both joined on 10-minute UTC bins.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "openmeteo" / "data"
sys.path.insert(0, str(ROOT))

from src.inverter_app.curtailment import (  # noqa: E402
    PvState,
    classify,
    estimate_mpp_voltages,
    has_battery_headroom,
)
from src.inverter_app.schemas import EnergySnapshotSchema  # noqa: E402

SNAPSHOTS_CSV = ROOT / "data" / "inverter_app_energysnapshot.csv"
SNAPSHOT_COLUMNS = [
    "timestamp",
    "id",
    "solar_power_w",
    "load_power_w",
    "grid_power_w",
    "battery_power_w",
    "battery_charge_pct",
    "battery_voltage_v",
    "grid_voltage_v",
    "battery_max_charge_current_a",
    "pv1_current_a",
    "pv1_power_w",
    "pv1_voltage_v",
    "pv2_current_a",
    "pv2_power_w",
    "pv2_voltage_v",
]
SATELLITE_GLOB ="openmeteo_satellite_radiation_seamless_hourly_*.csv"
WEATHER_GLOB = "openmeteo_archive_hourly_*.csv"
# Hourly sums over the preceding hour: every moment inside that hour gets
# the hour's value (mm/h).
WEATHER_SUMS = ["precipitation", "rain", "snowfall"]
WEATHER_CATEGORIES = ["weather_code"]
BIN = "10min"


def load_snapshots() -> pd.DataFrame:
    """Snapshots indexed by UTC time, with a curtailment `state` column."""
    df = pd.read_csv(SNAPSHOTS_CSV)
    if "timestamp" not in df.columns:
        # Headerless export: columns in DB table order.
        df = pd.read_csv(SNAPSHOTS_CSV, header=None, names=SNAPSHOT_COLUMNS)
    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        format="ISO8601",
        utc=True,
    )
    df = df.sort_values("timestamp").reset_index(drop=True)
    schemas = [
        EnergySnapshotSchema.model_validate(row)
        for row in df.to_dict("records")
    ]
    mpp = estimate_mpp_voltages(schemas)
    df["state"] = [classify(s, mpp).value for s in schemas]
    df["headroom"] = [has_battery_headroom(s) for s in schemas]
    return df.set_index("timestamp")


def load_satellite() -> pd.DataFrame:
    """
    Latest satellite CSV, UTC index. Non-instant columns are averages over
    the 10 minutes ending at the index time; `_instant` ones are at it.
    """
    path = sorted(DATA_DIR.glob(SATELLITE_GLOB))[-1]
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date")


def _bin_state(states: pd.Series) -> str:
    values = set(states)
    if not values or values == {PvState.DARK.value}:
        return PvState.DARK.value
    if PvState.CURTAILED.value in values:
        return PvState.CURTAILED.value
    if values <= {PvState.UNCONSTRAINED.value, PvState.DARK.value}:
        return PvState.UNCONSTRAINED.value
    return PvState.UNKNOWN.value


def load_joined() -> pd.DataFrame:
    """
    Snapshots averaged per 10-minute bin (labelled by bin end, like the
    satellite averages) joined with satellite irradiance. `state` is
    unconstrained only when every reading in the bin was.
    """
    snapshots = load_snapshots()
    numeric = snapshots.select_dtypes("number").drop(columns="id")
    numeric = numeric.drop(columns="headroom", errors="ignore")
    resample = dict(rule=BIN, label="right", closed="right")
    binned = numeric.resample(**resample).mean()
    binned["state"] = snapshots["state"].resample(**resample).agg(_bin_state)
    binned["readings"] = snapshots["state"].resample(**resample).size()
    binned = binned[binned["readings"] > 0]
    return binned.join(load_satellite(), how="inner")


def load_weather() -> pd.DataFrame:
    """Latest Open-Meteo archive (hourly weather) CSV, UTC index."""
    path = sorted(DATA_DIR.glob(WEATHER_GLOB))[-1]
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date")


def interpolate_weather(
    weather: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Hourly weather at arbitrary UTC times: linear in time for continuous
    values, the covering hour for sums, the nearest hour for categories.
    """
    continuous = weather.drop(columns=WEATHER_SUMS + WEATHER_CATEGORIES)
    union = continuous.index.union(index)
    result = (
        continuous.reindex(union)
        .interpolate(method="time", limit_area="inside")
        .reindex(index)
    )
    sums = weather[WEATHER_SUMS].reindex(index, method="bfill")
    categories = weather[WEATHER_CATEGORIES].reindex(index, method="nearest")
    return result.join(sums).join(categories)
