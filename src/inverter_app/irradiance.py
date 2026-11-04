"""
Plane-of-array irradiance for the PV array: measured by satellite
(Open-Meteo Satellite Radiation API) and the clear-sky ceiling (pvlib).
Proof of concept for estimating available PV power without loading panels.
"""

import os
from datetime import date

import pandas as pd
import pvlib
import requests
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
from pydantic import ValidationError

from src.inverter_app.schemas import PvSiteSchema

load_dotenv()

SATELLITE_API_URL = "https://satellite-api.open-meteo.com/v1/archive"
SATELLITE_GTI_VARIABLE = "global_tilted_irradiance_instant"
REQUEST_TIMEOUT_S = 30


def get_pv_site() -> PvSiteSchema:
    env = {
        "latitude": os.getenv("PV_SITE_LATITUDE"),
        "longitude": os.getenv("PV_SITE_LONGITUDE"),
        "tilt_deg": os.getenv("PV_SITE_TILT_DEG"),
        "azimuth_deg": os.getenv("PV_SITE_AZIMUTH_DEG"),
        "peak_power_w": os.getenv("PV_SITE_PEAK_POWER_W"),
        "performance_ratio": os.getenv("PV_SITE_PERFORMANCE_RATIO"),
    }
    try:
        return PvSiteSchema(**{k: v for k, v in env.items() if v})
    except ValidationError as e:
        raise ImproperlyConfigured(
            "Set PV_SITE_* keys in .env (see .env.example)"
        ) from e


def fetch_satellite_gti(
    site: PvSiteSchema,
    start: date,
    end: date,
) -> pd.Series:
    """
    Satellite-derived instantaneous GTI (W/m²) at native resolution
    (10-15 min), UTC index. Lags real time by ~20 min to a few hours.
    """
    params = {
        "latitude": site.latitude,
        "longitude": site.longitude,
        "hourly": SATELLITE_GTI_VARIABLE,
        "models": "satellite_radiation_seamless",
        "temporal_resolution": "native",
        "tilt": site.tilt_deg,
        # Open-Meteo azimuth: 0 = south, -90 = east, 90 = west.
        "azimuth": site.azimuth_deg - 180,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "UTC",
    }
    response = requests.get(
        SATELLITE_API_URL,
        params=params,
        timeout=REQUEST_TIMEOUT_S,
    )
    response.raise_for_status()
    hourly = response.json()["hourly"]
    index = pd.DatetimeIndex(pd.to_datetime(hourly["time"]), tz="UTC")
    return pd.Series(
        hourly[SATELLITE_GTI_VARIABLE],
        index=index,
        name="satellite_gti",
        dtype="float64",
    )


def clear_sky_gti(site: PvSiteSchema, times: pd.DatetimeIndex) -> pd.Series:
    """Cloudless-sky GTI (W/m²) on the array plane: a hard upper bound."""
    location = pvlib.location.Location(site.latitude, site.longitude)
    solar_position = location.get_solarposition(times)
    clearsky = location.get_clearsky(
        times,
        model="ineichen",
        solar_position=solar_position,
    )
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=site.tilt_deg,
        surface_azimuth=site.azimuth_deg,
        solar_zenith=solar_position["apparent_zenith"],
        solar_azimuth=solar_position["azimuth"],
        dni=clearsky["dni"],
        ghi=clearsky["ghi"],
        dhi=clearsky["dhi"],
    )
    return poa["poa_global"].fillna(0).clip(lower=0).rename("clear_sky_gti")


def gti_to_power_w(
    gti: pd.Series,
    site: PvSiteSchema,
    performance_ratio: float | None = None,
) -> pd.Series:
    ratio = performance_ratio or site.performance_ratio
    return gti / 1000 * site.peak_power_w * ratio
