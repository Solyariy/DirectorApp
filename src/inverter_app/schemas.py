from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EnergySnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None
    timestamp: datetime
    solar_power_w: int
    load_power_w: int
    # Positive = import from the grid, negative = export.
    grid_power_w: int
    # Positive = discharging, negative = charging.
    battery_power_w: int
    battery_charge_pct: int
    battery_voltage_v: float
    grid_voltage_v: float
    pv1_voltage_v: float | None = None
    pv1_current_a: float | None = None
    pv1_power_w: int | None = None
    pv2_voltage_v: float | None = None
    pv2_current_a: float | None = None
    pv2_power_w: int | None = None
    battery_max_charge_current_a: int | None = None


class PvSiteSchema(BaseModel):
    latitude: float
    longitude: float
    tilt_deg: float
    # Compass convention (pvlib): 180 = south, 90 = east, 270 = west.
    azimuth_deg: float
    peak_power_w: float
    # Losses between plane-of-array irradiance and inverter DC output.
    performance_ratio: float = 0.8
