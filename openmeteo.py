import os
from pathlib import Path

import openmeteo_requests

import pandas as pd
import requests_cache
from dotenv import load_dotenv
from retry_requests import retry

load_dotenv()
# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://satellite-api.open-meteo.com/v1/archive"
params = {
    "latitude": float(os.getenv("LATITUDE")),
    "longitude": float(os.getenv("LONGITUDE")),
    "daily": ["sunrise", "sunset", "sunshine_duration", "daylight_duration", "shortwave_radiation_sum"],
    "hourly": ["shortwave_radiation", "direct_radiation", "diffuse_radiation", "direct_normal_irradiance", "shortwave_radiation_clear_sky", "global_tilted_irradiance", "terrestrial_radiation", "terrestrial_radiation_instant", "global_tilted_irradiance_instant", "shortwave_radiation_clear_sky_instant", "direct_normal_irradiance_instant", "diffuse_radiation_instant", "shortwave_radiation_instant", "direct_radiation_instant", "sunshine_duration", "is_day"],
    "models": ["best_match", "satellite_radiation_seamless"],
    "timezone": "auto",
    "past_days": 31,
    "tilt": 40,
    "azimuth": 40,
    "temporal_resolution": "native",
}
responses = openmeteo.weather_api(url, params = params)

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok = True)


def save_dataset(dataframe: pd.DataFrame, model: str, kind: str) -> None:
    start = dataframe["date"].iloc[0].strftime("%Y-%m-%d")
    end = dataframe["date"].iloc[-1].strftime("%Y-%m-%d")
    path = DATA_DIR / f"openmeteo_{model}_{kind}_{start}_{end}.csv"
    dataframe.to_csv(path, index = False)
    print(f"Saved {len(dataframe)} rows to {path}")


# Process 1 location and 2 models (responses come in the order of params["models"])
for model, response in zip(params["models"], responses):
    print(f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E")
    print(f"Elevation: {response.Elevation()} m asl")
    print(f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}")
    print(f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s")
    print(f"Model Nº: {response.Model()}")

    # Process hourly data. The order of variables needs to be the same as requested.
    hourly = response.Hourly()
    hourly_shortwave_radiation = hourly.Variables(0).ValuesAsNumpy()
    hourly_direct_radiation = hourly.Variables(1).ValuesAsNumpy()
    hourly_diffuse_radiation = hourly.Variables(2).ValuesAsNumpy()
    hourly_direct_normal_irradiance = hourly.Variables(3).ValuesAsNumpy()
    hourly_shortwave_radiation_clear_sky = hourly.Variables(4).ValuesAsNumpy()
    hourly_global_tilted_irradiance = hourly.Variables(5).ValuesAsNumpy()
    hourly_terrestrial_radiation = hourly.Variables(6).ValuesAsNumpy()
    hourly_terrestrial_radiation_instant = hourly.Variables(7).ValuesAsNumpy()
    hourly_global_tilted_irradiance_instant = hourly.Variables(8).ValuesAsNumpy()
    hourly_shortwave_radiation_clear_sky_instant = hourly.Variables(9).ValuesAsNumpy()
    hourly_direct_normal_irradiance_instant = hourly.Variables(10).ValuesAsNumpy()
    hourly_diffuse_radiation_instant = hourly.Variables(11).ValuesAsNumpy()
    hourly_shortwave_radiation_instant = hourly.Variables(12).ValuesAsNumpy()
    hourly_direct_radiation_instant = hourly.Variables(13).ValuesAsNumpy()
    hourly_sunshine_duration = hourly.Variables(14).ValuesAsNumpy()
    hourly_is_day = hourly.Variables(15).ValuesAsNumpy()

    hourly_data = {
        "date": pd.date_range(
            start = pd.to_datetime(hourly.Time(), unit = "s", utc = True),
            end =  pd.to_datetime(hourly.TimeEnd(), unit = "s", utc = True),
            freq = pd.Timedelta(seconds = hourly.Interval()),
            inclusive = "left"
        ).tz_convert(response.Timezone().decode())
    }

    hourly_data["shortwave_radiation"] = hourly_shortwave_radiation
    hourly_data["direct_radiation"] = hourly_direct_radiation
    hourly_data["diffuse_radiation"] = hourly_diffuse_radiation
    hourly_data["direct_normal_irradiance"] = hourly_direct_normal_irradiance
    hourly_data["shortwave_radiation_clear_sky"] = hourly_shortwave_radiation_clear_sky
    hourly_data["global_tilted_irradiance"] = hourly_global_tilted_irradiance
    hourly_data["terrestrial_radiation"] = hourly_terrestrial_radiation
    hourly_data["terrestrial_radiation_instant"] = hourly_terrestrial_radiation_instant
    hourly_data["global_tilted_irradiance_instant"] = hourly_global_tilted_irradiance_instant
    hourly_data["shortwave_radiation_clear_sky_instant"] = hourly_shortwave_radiation_clear_sky_instant
    hourly_data["direct_normal_irradiance_instant"] = hourly_direct_normal_irradiance_instant
    hourly_data["diffuse_radiation_instant"] = hourly_diffuse_radiation_instant
    hourly_data["shortwave_radiation_instant"] = hourly_shortwave_radiation_instant
    hourly_data["direct_radiation_instant"] = hourly_direct_radiation_instant
    hourly_data["sunshine_duration"] = hourly_sunshine_duration
    hourly_data["is_day"] = hourly_is_day

    hourly_dataframe = pd.DataFrame(data = hourly_data)
    print("\nHourly data\n", hourly_dataframe)
    save_dataset(hourly_dataframe, model, "hourly")

    # Process daily data. The order of variables needs to be the same as requested.
    daily = response.Daily()
    daily_sunrise = daily.Variables(0).ValuesInt64AsNumpy()
    daily_sunset = daily.Variables(1).ValuesInt64AsNumpy()
    daily_sunshine_duration = daily.Variables(2).ValuesAsNumpy()
    daily_daylight_duration = daily.Variables(3).ValuesAsNumpy()
    daily_shortwave_radiation_sum = daily.Variables(4).ValuesAsNumpy()

    daily_data = {
        "date": pd.date_range(
            start = pd.to_datetime(daily.Time(), unit = "s", utc = True),
            end =  pd.to_datetime(daily.TimeEnd(), unit = "s", utc = True),
            freq = pd.Timedelta(seconds = daily.Interval()),
            inclusive = "left"
        ).tz_convert(response.Timezone().decode())
    }

    daily_data["sunrise"] = pd.to_datetime(daily_sunrise, unit = "s", utc = True).tz_convert(response.Timezone().decode())
    daily_data["sunset"] = pd.to_datetime(daily_sunset, unit = "s", utc = True).tz_convert(response.Timezone().decode())
    daily_data["sunshine_duration"] = daily_sunshine_duration
    daily_data["daylight_duration"] = daily_daylight_duration
    daily_data["shortwave_radiation_sum"] = daily_shortwave_radiation_sum

    daily_dataframe = pd.DataFrame(data = daily_data)
    print("\nDaily data\n", daily_dataframe)
    save_dataset(daily_dataframe, model, "daily")
