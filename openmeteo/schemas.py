from pydantic import BaseModel


class PvSiteSchema(BaseModel):
    latitude: float
    longitude: float
    tilt_deg: float
    # Compass convention (pvlib): 180 = south, 90 = east, 270 = west.
    azimuth_deg: float
    peak_power_w: float
    # Losses between plane-of-array irradiance and inverter DC output.
    performance_ratio: float = 0.8
