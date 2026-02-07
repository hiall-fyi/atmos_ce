"""Typed shapes for the forecast / air-quality payloads.

These are ``total=True`` TypedDicts: every key listed is always present
in the dict the matching ``parse_*`` producer builds (values may be
``None``, but the key exists). This lets mypy validate literal-key reads
in consumers while the payloads remain plain dicts at runtime.
"""
from __future__ import annotations

from typing import TypedDict


class CurrentConditions(TypedDict):
    """Output shape of ``OpenMeteoBackend.parse_current_conditions``."""

    temperature: float | None
    apparent_temperature: float | None
    dew_point: float | None
    humidity: float | None
    pressure: float | None
    surface_pressure: float | None
    wind_speed: float | None
    wind_direction: float | None
    wind_gusts: float | None
    precipitation: float | None
    rain: float | None
    showers: float | None
    snowfall: float | None
    cloud_cover: float | None
    cloud_cover_low: float | None
    cloud_cover_mid: float | None
    cloud_cover_high: float | None
    uv_index: float | None
    uv_index_clear_sky: float | None
    visibility: float | None
    cape: float | None
    lifted_index: float | None
    freezing_level_height: float | None
    soil_temperature_0cm: float | None
    soil_moisture_0_to_1cm: float | None
    temperature_500hpa: float | None
    temperature_700hpa: float | None
    wind_speed_500hpa: float | None
    wind_direction_500hpa: float | None
    geopotential_height_500hpa: float | None
    geopotential_height_700hpa: float | None
    condition: str
    weather_code: int
    is_day: int | None


class HourlyForecast(TypedDict):
    """One entry of ``OpenMeteoBackend.parse_hourly_forecast``."""

    datetime: str
    temperature: float | None
    apparent_temperature: float | None
    dew_point: float | None
    humidity: float | None
    pressure: float | None
    wind_speed: float | None
    wind_direction: float | None
    wind_gusts: float | None
    precipitation: float | None
    precipitation_probability: float | None
    cloud_cover: float | None
    visibility: float | None
    uv_index: float | None
    condition: str
    weather_code: int
    rain: float | None
    showers: float | None
    snowfall: float | None
    snow_depth: float | None
    cape: float | None


class DailyForecast(TypedDict):
    """One entry of ``OpenMeteoBackend.parse_daily_forecast``."""

    datetime: str
    temperature_max: float | None
    temperature_min: float | None
    apparent_temperature_max: float | None
    apparent_temperature_min: float | None
    precipitation_sum: float | None
    precipitation_probability_max: float | None
    precipitation_hours: float | None
    wind_speed_max: float | None
    wind_gusts_max: float | None
    wind_direction: float | None
    uv_index_max: float | None
    sunrise: str | None
    sunset: str | None
    condition: str
    weather_code: int


class AirQualityData(TypedDict):
    """Output shape of ``OpenMeteoBackend.parse_air_quality``."""

    european_aqi: float | None
    european_aqi_category: str | None
    european_aqi_color: str | None
    us_aqi: float | None
    us_aqi_category: str | None
    us_aqi_color: str | None
    pm10: float | None
    pm2_5: float | None
    carbon_monoxide: float | None
    nitrogen_dioxide: float | None
    sulphur_dioxide: float | None
    ozone: float | None
    carbon_dioxide: float | None


class ForecastPayload(TypedDict):
    """Aggregate forecast dict built by the coordinator."""

    current: CurrentConditions
    hourly: list[HourlyForecast]
    daily: list[DailyForecast]
