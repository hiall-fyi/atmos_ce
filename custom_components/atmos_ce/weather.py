"""Weather platform for Atmos CE.

Implements a weather entity with current conditions, hourly (48h),
and daily (7d) forecasts.  Created for any source with forecast enabled.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTRIBUTION_OPEN_METEO
from .coordinator import UnifiedCoordinator
from .entity import AtmosBaseEntity

if TYPE_CHECKING:
    from . import AtmosCEConfigEntry
    from .forecast_types import CurrentConditions, ForecastPayload

_LOGGER = logging.getLogger(__name__)

# Coordinator-based: no per-entity parallel updates needed
PARALLEL_UPDATES = 0


def _build_forecast(
    *,
    datetime: str,
    temperature: float | None,
    condition: str | None,
    precipitation: float | None,
    precipitation_probability: float | None,
    wind_speed: float | None,
    wind_bearing: float | None,
    templow: float | None = None,
) -> Forecast:
    """Assemble a HA ``Forecast`` from typed forecast-entry values.

    HA's ``Forecast`` TypedDict stub marks several numeric fields as
    ``NoneType`` (a known framework stub mismatch with the runtime, which
    accepts floats). Constructing it here, in one place, confines the
    single ``typeddict-item`` ignore to this boundary instead of
    scattering it across every call site.
    """
    return cast(
        "Forecast",
        {
            "datetime": datetime,
            "temperature": temperature,
            "templow": templow,
            "condition": condition,
            "precipitation": precipitation,
            "precipitation_probability": precipitation_probability,
            "wind_speed": wind_speed,
            "wind_bearing": wind_bearing,
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtmosCEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up weather entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        return

    # Gate weather entity on enable_forecast toggle
    if not coordinator.config.get("enable_forecast", True):
        return

    entry_id = entry.entry_id
    async_add_entities([AtmosWeatherEntity(coordinator, entry_id)])
    _LOGGER.debug("Added weather entity for %s", coordinator.source.source_name)


class AtmosWeatherEntity(AtmosBaseEntity, WeatherEntity):
    """Represent a weather forecast entity."""

    _attr_translation_key = "weather"
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    # Always use metric native units, HA converts for the user
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        entry_id: str,
    ) -> None:
        """Initialize the AtmosWeatherEntity."""
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_weather"
        self._attr_attribution = ATTRIBUTION_OPEN_METEO

    @property
    def available(self) -> bool:
        """Return True when the coordinator succeeded and a forecast is present.

        Availability tracks the forecast payload, not the current block:
        the hourly/daily lists stay usable even when current conditions
        are empty, and the current-conditions properties None-guard.
        """
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data
        return data is not None and data.forecast is not None

    # -- Current conditions --

    @property
    def native_temperature(self) -> float | None:
        """Return the current temperature."""
        current = self._current
        return current["temperature"] if current else None

    @property
    def native_pressure(self) -> float | None:
        """Return the current pressure."""
        current = self._current
        return current["pressure"] if current else None

    @property
    def humidity(self) -> float | None:
        """Return the current humidity."""
        current = self._current
        return current["humidity"] if current else None

    @property
    def native_wind_speed(self) -> float | None:
        """Return the current wind speed."""
        current = self._current
        return current["wind_speed"] if current else None

    @property
    def wind_bearing(self) -> float | None:
        """Return the current wind bearing."""
        current = self._current
        return current["wind_direction"] if current else None

    @property
    def condition(self) -> str | None:
        """Return the current weather condition."""
        current = self._current
        return current["condition"] if current else None

    @property
    def native_apparent_temperature(self) -> float | None:
        """Return the current apparent temperature."""
        current = self._current
        return current["apparent_temperature"] if current else None

    @property
    def native_dew_point(self) -> float | None:
        """Return the current dew point."""
        current = self._current
        return current["dew_point"] if current else None

    @property
    def native_visibility(self) -> float | None:
        """Return the current visibility."""
        current = self._current
        return current["visibility"] if current else None

    @property
    def ozone(self) -> float | None:
        """Return the current ozone level.

        Returns None when the enable_air_quality toggle is off or the
        air-quality fetch failed.
        """
        data = self.coordinator.data
        if not data or not data.air_quality:
            return None
        return data.air_quality["ozone"]

    # -- Forecasts --

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast."""
        forecast = self._forecast_data
        hourly = forecast.get("hourly") if forecast else None
        if not hourly:
            return None
        return [
            _build_forecast(
                datetime=h["datetime"],
                temperature=h["temperature"],
                condition=h["condition"],
                precipitation=h["precipitation"],
                precipitation_probability=h["precipitation_probability"],
                wind_speed=h["wind_speed"],
                wind_bearing=h["wind_direction"],
            )
            for h in hourly[:48]
        ]

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast."""
        forecast = self._forecast_data
        daily = forecast.get("daily") if forecast else None
        if not daily:
            return None
        return [
            _build_forecast(
                datetime=d["datetime"],
                temperature=d["temperature_max"],
                templow=d["temperature_min"],
                condition=d["condition"],
                precipitation=d["precipitation_sum"],
                precipitation_probability=d["precipitation_probability_max"],
                wind_speed=d["wind_speed_max"],
                wind_bearing=d["wind_direction"],
            )
            for d in daily[:7]
        ]

    # -- Private helpers --

    @property
    def _forecast_data(self) -> ForecastPayload | None:
        """Return forecast dict from coordinator data."""
        data = self.coordinator.data
        return data.forecast if data else None

    @property
    def _current(self) -> CurrentConditions | None:
        """Return current conditions dict, or None if unavailable."""
        forecast = self._forecast_data
        return forecast.get("current") if forecast else None
