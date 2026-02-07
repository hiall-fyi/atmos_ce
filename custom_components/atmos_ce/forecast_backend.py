"""Internal forecast engine backed by Open-Meteo.

This module provides the ``OpenMeteoBackend`` class which encapsulates
all forecast, current-conditions, and air-quality fetch/parse logic
using the Open-Meteo API.  It is used by ``UnifiedCoordinator`` as an
internal implementation detail, not exposed as a user-facing source.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp

from .http_retry import async_fetch_with_retry

if TYPE_CHECKING:
    from .forecast_types import (
        AirQualityData,
        CurrentConditions,
        DailyForecast,
        HourlyForecast,
    )

_LOGGER = logging.getLogger(__name__)


def _normalise_iso_to_utc(
    raw: str | None,
    utc_offset_seconds: int,
) -> str | None:
    """Convert Open-Meteo's naive local ISO string to tz-aware UTC ISO.

    Open-Meteo is called with ``timezone=auto`` so ``hourly.time[i]`` and
    ``daily.time[i]`` are **naive** local times (e.g. ``"2026-05-09T14:00"``).
    HA's weather platform requires ``Forecast.datetime`` to be tz-aware
    (or an ISO-8601 string with offset). Feeding a naive string makes HA
    treat every hour as UTC and shift non-UTC users' forecast by their
    timezone offset.

    Given the ``utc_offset_seconds`` the API returns alongside the data,
    we can pin each timestamp to a fixed offset then normalise to UTC
    (HA accepts either form, UTC is stable across DST at the timezone
    boundary).

    Args:
        raw: Naive ISO string from the Open-Meteo response, or None.
        utc_offset_seconds: ``data["utc_offset_seconds"]`` from the same
            response. Defaults to 0 when the API omits the field.

    Returns:
        ``"2026-05-09T12:00:00+00:00"``-style UTC ISO string, or None if
        the input was empty/unparseable (caller decides fallback).

    """
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        tz = timezone(timedelta(seconds=utc_offset_seconds))
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(UTC).isoformat()

# Unit conversion factor (for values not handled by Open-Meteo API params)
_METERS_TO_KM: float = 1 / 1000

# AQI category lookup tables, (threshold, category, color).
# Walk the tuple in order; the first entry whose threshold >= value wins.
_EUROPEAN_AQI_CATEGORIES: tuple[tuple[int, str, str], ...] = (
    (20, "Good", "green"),
    (40, "Fair", "yellow"),
    (60, "Moderate", "orange"),
    (80, "Poor", "red"),
    (100, "Very Poor", "purple"),
    (999_999, "Extremely Poor", "maroon"),
)

_US_AQI_CATEGORIES: tuple[tuple[int, str, str], ...] = (
    (50, "Good", "green"),
    (100, "Moderate", "yellow"),
    (150, "Unhealthy for Sensitive Groups", "orange"),
    (200, "Unhealthy", "red"),
    (300, "Very Unhealthy", "purple"),
    (999_999, "Hazardous", "maroon"),
)


_AQ_PARAMS: tuple[str, ...] = (
    "european_aqi",
    "us_aqi",
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "carbon_dioxide",
)


def _classify_aqi(
    value: float | None,
    table: tuple[tuple[int, str, str], ...],
) -> tuple[str | None, str | None]:
    """Look up AQI category and color from a threshold table.

    Args:
        value: Raw AQI index value (``None`` → no classification).
        table: Ordered sequence of ``(threshold, category, color)`` tuples.

    Returns:
        ``(category, color)`` or ``(None, None)`` when *value* is ``None``.

    """
    if value is None:
        return None, None
    for threshold, category, color in table:
        if value <= threshold:
            return category, color
    last = table[-1]
    return last[1], last[2]


def _safe_get(
    data: dict[str, Any],
    key: str,
    index: int,
    default: Any = None,  # noqa: ANN401 — generic default
) -> Any:  # noqa: ANN401 — generic return
    """Safely get a value from an Open-Meteo array field.

    Args:
        data: The hourly/daily dict from the API response.
        key: The field name (e.g. ``"temperature_2m"``).
        index: The array index to retrieve.
        default: Fallback value if out of bounds or missing.

    Returns:
        The value at *index*, or *default*.

    """
    arr = data.get(key, [])
    return arr[index] if index < len(arr) else default


def _derive_is_day_from_local_time(iso_time: str | None) -> int | None:
    """Guess ``is_day`` from the hour component of an Open-Meteo local time.

    Open-Meteo is called with ``timezone=auto`` so ``hourly.time[i]`` is a
    naive local ISO string (e.g. ``"2026-05-10T03:00"``). When the API
    response omits ``is_day`` we fall back to a day-window heuristic
    rather than defaulting to daytime, which would render every
    overnight clear-sky hour as "sunny" on the weather card.

    The window 06:00–17:59 local approximates civil daylight well enough
    for fallback purposes; at high latitudes the heuristic is wrong near
    solstices, but Open-Meteo reliably returns ``is_day`` there in
    practice and users notice polar-region icons less than everyone
    else noticing a 2am sun.

    Args:
        iso_time: Naive local ISO string from the Open-Meteo response, or
            ``None``.

    Returns:
        ``1`` / ``0`` when the hour can be parsed, ``None`` otherwise
        (callers keep the current "treat as day" default in that case).

    """
    if not iso_time:
        return None
    try:
        parsed = datetime.fromisoformat(iso_time)
    except ValueError:
        return None
    return 1 if 6 <= parsed.hour < 18 else 0


class OpenMeteoBackend:
    """Internal forecast engine backed by Open-Meteo.

    Encapsulates all forecast, current-conditions, and air-quality
    fetch/parse logic.  Used by ``UnifiedCoordinator`` for all source
    types, not a user-facing source.
    """

    API_URL: ClassVar[str] = "https://api.open-meteo.com/v1/forecast"
    AIR_QUALITY_URL: ClassVar[str] = "https://air-quality-api.open-meteo.com/v1/air-quality"

    # WMO weather code → HA condition mapping
    WEATHER_CODE_MAP: ClassVar[dict[int, str]] = {
        0: "sunny",
        1: "partlycloudy",
        2: "partlycloudy",
        3: "cloudy",
        45: "fog",
        48: "fog",
        51: "rainy",
        53: "rainy",
        55: "rainy",
        56: "rainy",
        57: "rainy",
        61: "rainy",
        63: "rainy",
        65: "pouring",
        66: "snowy-rainy",
        67: "snowy-rainy",
        71: "snowy",
        73: "snowy",
        75: "snowy",
        77: "snowy",
        80: "rainy",
        81: "rainy",
        82: "pouring",
        85: "snowy",
        86: "snowy",
        95: "lightning",
        96: "lightning-rainy",
        99: "lightning-rainy",
    }

    @staticmethod
    def validate_coordinates(latitude: float, longitude: float) -> None:
        """Validate geographic coordinates.

        Args:
            latitude: Location latitude (-90 to 90).
            longitude: Location longitude (-180 to 180).

        Raises:
            ValueError: If coordinates are out of range.

        """
        if not -90 <= latitude <= 90:
            raise ValueError(
                f"Invalid latitude: {latitude} (must be -90 to 90)",
            )
        if not -180 <= longitude <= 180:
            raise ValueError(
                f"Invalid longitude: {longitude} (must be -180 to 180)",
            )

    async def fetch_forecast(
        self,
        session: aiohttp.ClientSession,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
        """Fetch complete weather forecast from Open-Meteo API.

        Args:
            session: aiohttp client session.
            latitude: Location latitude.
            longitude: Location longitude.

        Returns:
            Raw forecast data dictionary.

        """
        self.validate_coordinates(latitude, longitude)
        _LOGGER.debug("Fetching forecast from Open-Meteo for lat=%s, lon=%s", latitude, longitude)

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join([
                "temperature_2m", "relative_humidity_2m", "apparent_temperature",
                "dew_point_2m", "is_day", "precipitation", "rain", "showers",
                "snowfall", "weather_code", "cloud_cover", "cloud_cover_low",
                "cloud_cover_mid", "cloud_cover_high", "pressure_msl",
                "surface_pressure", "wind_speed_10m", "wind_direction_10m",
                "wind_gusts_10m", "uv_index", "uv_index_clear_sky", "visibility",
                "cape", "lifted_index", "freezing_level_height",
                "soil_temperature_0cm", "soil_moisture_0_to_1cm",
                # Pressure-level variables for stability calculations
                "temperature_500hPa", "temperature_700hPa",
                "wind_speed_500hPa", "wind_direction_500hPa",
                "geopotential_height_500hPa", "geopotential_height_700hPa",
            ]),
            "hourly": ",".join([
                "temperature_2m", "relative_humidity_2m", "dew_point_2m",
                "apparent_temperature", "precipitation_probability", "precipitation",
                "rain", "showers", "snowfall", "snow_depth", "weather_code",
                "pressure_msl", "surface_pressure", "cloud_cover", "visibility",
                "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "uv_index",
                "cape", "is_day",
            ]),
            "daily": ",".join([
                "weather_code", "temperature_2m_max", "temperature_2m_min",
                "apparent_temperature_max", "apparent_temperature_min",
                "sunrise", "sunset", "uv_index_max", "precipitation_sum",
                "rain_sum", "showers_sum", "snowfall_sum", "precipitation_hours",
                "precipitation_probability_max", "wind_speed_10m_max",
                "wind_gusts_10m_max", "wind_direction_10m_dominant",
            ]),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "timezone": "auto",
            "forecast_days": 7,
            "past_days": 0,
        }

        response = await async_fetch_with_retry(
            session, self.API_URL, params=params,
            source_label="Open-Meteo", logger=_LOGGER,
        )
        async with response:
            data = await response.json()

        _LOGGER.debug("Successfully fetched Open-Meteo forecast")
        return data

    def parse_current_conditions(
        self,
        data: dict[str, Any],
    ) -> CurrentConditions:
        """Parse current weather conditions from Open-Meteo response.

        Args:
            data: Open-Meteo API response.

        Returns:
            Dictionary of current condition values.

        """
        current = data.get("current", {})
        weather_code = current.get("weather_code", 0)
        # is_day absent → derive from local time of the current block so
        # a clear-sky code at 03:00 does not render as "sunny".
        is_day = current.get("is_day")
        if is_day is None:
            is_day = _derive_is_day_from_local_time(current.get("time"))
        condition = self._map_weather_code(weather_code, is_day)

        pressure_msl = current.get("pressure_msl")
        surface_pressure = current.get("surface_pressure")
        visibility = current.get("visibility")
        if visibility is not None:
            visibility = round(visibility * _METERS_TO_KM, 2)

        return {
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "dew_point": current.get("dew_point_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "pressure": round(pressure_msl, 2) if pressure_msl is not None else None,
            "surface_pressure": round(surface_pressure, 2) if surface_pressure is not None else None,
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "wind_gusts": current.get("wind_gusts_10m"),
            "precipitation": current.get("precipitation"),
            "rain": current.get("rain"),
            "showers": current.get("showers"),
            "snowfall": current.get("snowfall"),
            "cloud_cover": current.get("cloud_cover"),
            "cloud_cover_low": current.get("cloud_cover_low"),
            "cloud_cover_mid": current.get("cloud_cover_mid"),
            "cloud_cover_high": current.get("cloud_cover_high"),
            "uv_index": current.get("uv_index"),
            "uv_index_clear_sky": current.get("uv_index_clear_sky"),
            "visibility": visibility,
            "cape": current.get("cape"),
            "lifted_index": current.get("lifted_index"),
            "freezing_level_height": current.get("freezing_level_height"),
            "soil_temperature_0cm": current.get("soil_temperature_0cm"),
            "soil_moisture_0_to_1cm": current.get("soil_moisture_0_to_1cm"),
            # Pressure-level data for stability calculations
            "temperature_500hpa": current.get("temperature_500hPa"),
            "temperature_700hpa": current.get("temperature_700hPa"),
            "wind_speed_500hpa": current.get("wind_speed_500hPa"),
            "wind_direction_500hpa": current.get("wind_direction_500hPa"),
            "geopotential_height_500hpa": current.get("geopotential_height_500hPa"),
            "geopotential_height_700hpa": current.get("geopotential_height_700hPa"),
            "condition": condition,
            "weather_code": weather_code,
            "is_day": is_day,
        }

    def parse_hourly_forecast(
        self,
        data: dict[str, Any],
        hours: int = 48,
    ) -> list[HourlyForecast]:
        """Parse hourly forecast from Open-Meteo response.

        Args:
            data: Open-Meteo API response.
            hours: Number of hours to include.

        Returns:
            List of hourly forecast dictionaries.

        """
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return []

        utc_offset = data.get("utc_offset_seconds", 0) or 0
        times = times[:hours]
        forecasts = []
        for i, time in enumerate(times):
            weather_code = _safe_get(hourly, "weather_code", i, 0)
            # Open-Meteo returns is_day as 1/0 when requested in `hourly`.
            # When the field is absent (older responses / API variant)
            # fall back to the hour component of the local time so an
            # overnight clear-sky code does not render as "sunny".
            is_day = _safe_get(hourly, "is_day", i, None)
            if is_day is None:
                is_day = _derive_is_day_from_local_time(time)
            condition = self._map_weather_code(weather_code, is_day)

            pressure = _safe_get(hourly, "pressure_msl", i)
            visibility = _safe_get(hourly, "visibility", i)
            if visibility is not None:
                visibility = round(visibility * _METERS_TO_KM, 2)

            forecasts.append({
                "datetime": _normalise_iso_to_utc(time, utc_offset) or time,
                "temperature": _safe_get(hourly, "temperature_2m", i),
                "apparent_temperature": _safe_get(hourly, "apparent_temperature", i),
                "dew_point": _safe_get(hourly, "dew_point_2m", i),
                "humidity": _safe_get(hourly, "relative_humidity_2m", i),
                "pressure": pressure,
                "wind_speed": _safe_get(hourly, "wind_speed_10m", i),
                "wind_direction": _safe_get(hourly, "wind_direction_10m", i),
                "wind_gusts": _safe_get(hourly, "wind_gusts_10m", i),
                "precipitation": _safe_get(hourly, "precipitation", i),
                "precipitation_probability": _safe_get(hourly, "precipitation_probability", i),
                "cloud_cover": _safe_get(hourly, "cloud_cover", i),
                "visibility": visibility,
                "uv_index": _safe_get(hourly, "uv_index", i),
                "condition": condition,
                "weather_code": weather_code,
                # Precipitation type breakdown
                "rain": _safe_get(hourly, "rain", i),
                "showers": _safe_get(hourly, "showers", i),
                "snowfall": _safe_get(hourly, "snowfall", i),
                "snow_depth": _safe_get(hourly, "snow_depth", i),
                # Storm potential
                "cape": _safe_get(hourly, "cape", i),
            })
        return forecasts

    def parse_daily_forecast(
        self,
        data: dict[str, Any],
        days: int = 7,
    ) -> list[DailyForecast]:
        """Parse daily forecast from Open-Meteo response.

        Args:
            data: Open-Meteo API response.
            days: Number of days to include.

        Returns:
            List of daily forecast dictionaries.

        """
        daily = data.get("daily", {})
        times = daily.get("time", [])
        if not times:
            return []

        utc_offset = data.get("utc_offset_seconds", 0) or 0
        times = times[:days]
        forecasts = []
        for i, time in enumerate(times):
            weather_code = _safe_get(daily, "weather_code", i, 0)
            condition = self._map_weather_code(weather_code, is_day=1)
            forecasts.append({
                "datetime": _normalise_iso_to_utc(time, utc_offset) or time,
                "temperature_max": _safe_get(daily, "temperature_2m_max", i),
                "temperature_min": _safe_get(daily, "temperature_2m_min", i),
                "apparent_temperature_max": _safe_get(daily, "apparent_temperature_max", i),
                "apparent_temperature_min": _safe_get(daily, "apparent_temperature_min", i),
                "precipitation_sum": _safe_get(daily, "precipitation_sum", i),
                "precipitation_probability_max": _safe_get(daily, "precipitation_probability_max", i),
                "precipitation_hours": _safe_get(daily, "precipitation_hours", i),
                "wind_speed_max": _safe_get(daily, "wind_speed_10m_max", i),
                "wind_gusts_max": _safe_get(daily, "wind_gusts_10m_max", i),
                "wind_direction": _safe_get(daily, "wind_direction_10m_dominant", i),
                "uv_index_max": _safe_get(daily, "uv_index_max", i),
                "sunrise": _safe_get(daily, "sunrise", i),
                "sunset": _safe_get(daily, "sunset", i),
                "condition": condition,
                "weather_code": weather_code,
            })
        return forecasts

    def _map_weather_code(
        self, weather_code: int, is_day: int | None = 1,
    ) -> str:
        """Map Open-Meteo weather code to Home Assistant condition.

        Args:
            weather_code: WMO weather code.
            is_day: ``1`` if daytime, ``0`` if nighttime, ``None`` if
                unknown. When ``None`` the clear-sky code is rendered
                as ``"clear-night"`` rather than ``"sunny"``, the
                night icon looks sensible in daylight, but a bright-sun
                icon at 3 a.m. is an obvious defect.

        Returns:
            Home Assistant condition name.

        """
        condition = self.WEATHER_CODE_MAP.get(weather_code, "exceptional")
        if condition == "sunny" and is_day != 1:
            condition = "clear-night"
        return condition

    async def fetch_air_quality(
        self,
        session: aiohttp.ClientSession,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
        """Fetch air quality data from Open-Meteo Air Quality API.

        Args:
            session: aiohttp client session.
            latitude: Location latitude.
            longitude: Location longitude.

        Returns:
            Raw air quality data dictionary.

        """
        self.validate_coordinates(latitude, longitude)
        _LOGGER.debug("Fetching air quality from Open-Meteo for lat=%s, lon=%s", latitude, longitude)

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(_AQ_PARAMS),
            "hourly": ",".join(_AQ_PARAMS),
            "timezone": "auto",
            "forecast_days": 5,
        }

        response = await async_fetch_with_retry(
            session, self.AIR_QUALITY_URL, params=params,
            source_label="Open-Meteo", logger=_LOGGER,
        )
        async with response:
            data = await response.json()

        _LOGGER.debug("Successfully fetched Open-Meteo air quality data")
        return data

    def parse_air_quality(
        self,
        data: dict[str, Any],
    ) -> AirQualityData:
        """Parse current air quality from Open-Meteo response.

        Args:
            data: Open-Meteo Air Quality API response.

        Returns:
            Dictionary of current air quality values.

        """
        current = data.get("current", {})
        european_aqi = current.get("european_aqi")
        us_aqi = current.get("us_aqi")

        european_aqi_category, european_aqi_color = _classify_aqi(
            european_aqi, _EUROPEAN_AQI_CATEGORIES,
        )
        us_aqi_category, us_aqi_color = _classify_aqi(
            us_aqi, _US_AQI_CATEGORIES,
        )

        return {
            "european_aqi": european_aqi,
            "european_aqi_category": european_aqi_category,
            "european_aqi_color": european_aqi_color,
            "us_aqi": us_aqi,
            "us_aqi_category": us_aqi_category,
            "us_aqi_color": us_aqi_color,
            "pm10": current.get("pm10"),
            "pm2_5": current.get("pm2_5"),
            "carbon_monoxide": current.get("carbon_monoxide"),
            "nitrogen_dioxide": current.get("nitrogen_dioxide"),
            "sulphur_dioxide": current.get("sulphur_dioxide"),
            "ozone": current.get("ozone"),
            "carbon_dioxide": current.get("carbon_dioxide"),
        }

    async def validate_api_access(
        self,
        session: aiohttp.ClientSession,
        latitude: float = 51.5074,
        longitude: float = -0.1278,
    ) -> tuple[bool, str | None]:
        """Validate Open-Meteo API access with a test request.

        Args:
            session: aiohttp client session.
            latitude: Test latitude (default London).
            longitude: Test longitude (default London).

        Returns:
            Tuple of (success, error_message).

        """
        try:
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m",
                "forecast_days": 1,
            }
            response = await async_fetch_with_retry(
                session, self.API_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
                source_label="Open-Meteo", logger=_LOGGER,
            )
            async with response:
                data = await response.json()
                if "current" not in data:
                    return False, "Invalid API response structure"
            return True, None
        except aiohttp.ClientError as err:
            return False, f"Failed to connect to Open-Meteo: {err}"
