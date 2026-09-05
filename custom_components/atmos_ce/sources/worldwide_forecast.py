"""Worldwide Forecast source (forecast-only, no warnings).

This source provides forecasts, air quality, and astronomical data
for any location worldwide.  It has no warning backend, users in
countries without a dedicated warning source can use this to get
weather data from Atmos CE.

Internally powered by Open-Meteo via ``OpenMeteoBackend``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from ..const import (
    FORECAST_ONLY_UPDATE_INTERVAL_MIN,
    MAX_UPDATE_INTERVAL_MIN,
    MIN_UPDATE_INTERVAL_MIN,
)
from ..forecast_backend import OpenMeteoBackend
from ..models import Alert
from ..source_base import WeatherWarningSource

_LOGGER = logging.getLogger(__name__)

# Shared backend instance for config validation.
_BACKEND = OpenMeteoBackend()


class WorldwideForecastSource(WeatherWarningSource):
    """Worldwide Forecast source (no warning backend).

    Provides forecasts, air quality, and astronomical data for any
    location.  Warning entities are never created for this source.
    """

    @property
    def has_warning_backend(self) -> bool:
        """Return False, this source has no warning backend."""
        return False

    @property
    def source_id(self) -> str:
        """Return the unique identifier for this source."""
        return "worldwide_forecast"

    @property
    def source_name(self) -> str:
        """Return the human-readable name for this source."""
        return "Worldwide Forecast"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Return empty list, this source has no warning backend."""
        return []

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing Open-Meteo API access."""
        latitude = config.get("forecast_latitude")
        longitude = config.get("forecast_longitude")

        if latitude is not None and longitude is not None:
            try:
                _BACKEND.validate_coordinates(float(latitude), float(longitude))
            except (ValueError, TypeError) as err:
                return False, str(err)
            return await _BACKEND.validate_api_access(
                session, float(latitude), float(longitude),
            )

        return await _BACKEND.validate_api_access(session)

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for this source.

        Only ``enabled``/``update_interval``: unlike ``common_config_schema``,
        this source has no ``location_filters`` (nothing to filter, it has
        no warning backend). Forecast location + ``location_name`` are
        collected by config_flow's separate ``forecast_location`` step, not
        this schema.
        """
        return vol.Schema({
            vol.Optional("enabled", default=True): cv.boolean,
            vol.Optional(
                "update_interval", default=FORECAST_ONLY_UPDATE_INTERVAL_MIN,
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_UPDATE_INTERVAL_MIN, max=MAX_UPDATE_INTERVAL_MIN),
            ),
        })
