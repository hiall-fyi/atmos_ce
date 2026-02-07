"""Forecast and air-quality sensor entities."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)

from ..entity import AtmosDescriptionEntity


@dataclass(frozen=True, kw_only=True)
class WeatherForecastSensorDescription(SensorEntityDescription):
    """Describe a forecast sensor with data-key and optional value transform."""

    data_key: str
    data_source: str = "current"
    value_fn: Callable[[float | None], float | None] | None = None


FORECAST_SENSORS: tuple[WeatherForecastSensorDescription, ...] = (
    WeatherForecastSensorDescription(
        key="temperature", translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="temperature", native_unit_of_measurement="°C",
    ),
    WeatherForecastSensorDescription(
        key="apparent_temperature", translation_key="apparent_temperature",
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="apparent_temperature", native_unit_of_measurement="°C",
    ),
    WeatherForecastSensorDescription(
        key="dew_point", translation_key="dew_point",
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="dew_point", native_unit_of_measurement="°C",
    ),
    WeatherForecastSensorDescription(
        key="humidity", translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY, state_class=SensorStateClass.MEASUREMENT,
        data_key="humidity", native_unit_of_measurement="%",
    ),
    WeatherForecastSensorDescription(
        key="pressure", translation_key="pressure",
        device_class=SensorDeviceClass.PRESSURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="pressure", native_unit_of_measurement="hPa",
    ),
    WeatherForecastSensorDescription(
        key="surface_pressure", translation_key="surface_pressure",
        device_class=SensorDeviceClass.PRESSURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="surface_pressure", native_unit_of_measurement="hPa",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="wind_speed", translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED, state_class=SensorStateClass.MEASUREMENT,
        data_key="wind_speed", native_unit_of_measurement="km/h",
    ),
    WeatherForecastSensorDescription(
        key="wind_direction", translation_key="wind_direction",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="wind_direction", native_unit_of_measurement="°",
    ),
    WeatherForecastSensorDescription(
        key="wind_gusts", translation_key="wind_gusts",
        device_class=SensorDeviceClass.WIND_SPEED, state_class=SensorStateClass.MEASUREMENT,
        data_key="wind_gusts", native_unit_of_measurement="km/h",
    ),
    WeatherForecastSensorDescription(
        key="precipitation", translation_key="precipitation",
        device_class=SensorDeviceClass.PRECIPITATION, state_class=SensorStateClass.MEASUREMENT,
        data_key="precipitation", native_unit_of_measurement="mm",
    ),
    WeatherForecastSensorDescription(
        key="rain", translation_key="rain",
        device_class=SensorDeviceClass.PRECIPITATION, state_class=SensorStateClass.MEASUREMENT,
        data_key="rain", native_unit_of_measurement="mm",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="showers", translation_key="showers",
        device_class=SensorDeviceClass.PRECIPITATION, state_class=SensorStateClass.MEASUREMENT,
        data_key="showers", native_unit_of_measurement="mm",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="snowfall", translation_key="snowfall",
        device_class=SensorDeviceClass.PRECIPITATION, state_class=SensorStateClass.MEASUREMENT,
        data_key="snowfall", native_unit_of_measurement="cm",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="cloud_cover", translation_key="cloud_cover",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="cloud_cover", native_unit_of_measurement="%",
    ),
    WeatherForecastSensorDescription(
        key="cloud_cover_low", translation_key="cloud_cover_low",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="cloud_cover_low", native_unit_of_measurement="%",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="cloud_cover_mid", translation_key="cloud_cover_mid",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="cloud_cover_mid", native_unit_of_measurement="%",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="cloud_cover_high", translation_key="cloud_cover_high",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="cloud_cover_high", native_unit_of_measurement="%",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="uv_index", translation_key="uv_index",
        state_class=SensorStateClass.MEASUREMENT, data_key="uv_index",
    ),
    WeatherForecastSensorDescription(
        key="uv_index_clear_sky", translation_key="uv_index_clear_sky",
        state_class=SensorStateClass.MEASUREMENT, data_key="uv_index_clear_sky",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="visibility", translation_key="visibility",
        device_class=SensorDeviceClass.DISTANCE, state_class=SensorStateClass.MEASUREMENT,
        data_key="visibility", native_unit_of_measurement="km",
    ),
    WeatherForecastSensorDescription(
        key="cape", translation_key="cape",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="cape", native_unit_of_measurement="J/kg",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="lifted_index", translation_key="lifted_index",
        state_class=SensorStateClass.MEASUREMENT, data_key="lifted_index",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="freezing_level_height", translation_key="freezing_level_height",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="freezing_level_height", native_unit_of_measurement="m",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="soil_temperature", translation_key="soil_temperature",
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="soil_temperature_0cm", native_unit_of_measurement="°C",
        entity_registry_enabled_default=False,
    ),
    WeatherForecastSensorDescription(
        key="soil_moisture", translation_key="soil_moisture",
        device_class=SensorDeviceClass.MOISTURE, state_class=SensorStateClass.MEASUREMENT,
        data_key="soil_moisture_0_to_1cm", native_unit_of_measurement="%",
        # Open-Meteo reports soil moisture as a 0.0-1.0 volumetric
        # fraction (m³/m³); HA's MOISTURE device class expects %.
        value_fn=lambda v: round(v * 100, 1) if v is not None else None,
        entity_registry_enabled_default=False,
    ),
)


AIR_QUALITY_SENSORS: tuple[WeatherForecastSensorDescription, ...] = (
    WeatherForecastSensorDescription(
        key="european_aqi", translation_key="european_aqi",
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement="EAQI",
        data_key="european_aqi", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="us_aqi", translation_key="us_aqi",
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement="AQI",
        data_key="us_aqi", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="pm25", translation_key="pm25",
        device_class=SensorDeviceClass.PM25, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="μg/m³", data_key="pm2_5", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="pm10", translation_key="pm10",
        device_class=SensorDeviceClass.PM10, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="μg/m³", data_key="pm10", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="nitrogen_dioxide", translation_key="nitrogen_dioxide",
        device_class=SensorDeviceClass.NITROGEN_DIOXIDE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="μg/m³", data_key="nitrogen_dioxide", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="ozone", translation_key="ozone",
        device_class=SensorDeviceClass.OZONE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="μg/m³", data_key="ozone", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="sulphur_dioxide", translation_key="sulphur_dioxide",
        device_class=SensorDeviceClass.SULPHUR_DIOXIDE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="μg/m³", data_key="sulphur_dioxide", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="carbon_monoxide", translation_key="carbon_monoxide",
        device_class=SensorDeviceClass.CO, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="μg/m³", data_key="carbon_monoxide", data_source="air_quality",
    ),
    WeatherForecastSensorDescription(
        key="carbon_dioxide", translation_key="carbon_dioxide",
        device_class=SensorDeviceClass.CO2, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="ppm", data_key="carbon_dioxide", data_source="air_quality",
    ),
)


class WeatherForecastSensor(AtmosDescriptionEntity, SensorEntity):
    """Represent a forecast sensor driven by a WeatherForecastSensorDescription."""

    entity_description: WeatherForecastSensorDescription

    @property
    def available(self) -> bool:
        """Return True when the backing data slice for this sensor is present."""
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data
        if data is None:
            return False
        if self.entity_description.data_source == "air_quality":
            return data.air_quality is not None
        # Truthiness, not membership: an empty current block has no value
        # to serve, so availability must match what native_value returns.
        return bool(data.forecast and data.forecast.get("current"))

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value from coordinator data."""
        data = self.coordinator.data
        if not data:
            return None
        source = self.entity_description.data_source
        if source == "air_quality":
            container = data.air_quality
        else:
            container = data.forecast.get("current") if data.forecast else None
        if not container:
            return None
        raw = container.get(self.entity_description.data_key)
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(raw)
        return raw

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for AQI sensors (category/color)."""
        key = self.entity_description.data_key
        data = self.coordinator.data
        if (
            self.entity_description.data_source == "air_quality"
            and key in ("european_aqi", "us_aqi")
            and data
            and data.air_quality
        ):
            # Literal-key branches (not an f-string lookup) so the typed
            # AirQualityData keys are checked by mypy. `key` is guarded to
            # the two AQI keys above, so these are the only cases.
            aq = data.air_quality
            if key == "european_aqi":
                return {
                    "category": aq["european_aqi_category"],
                    "color": aq["european_aqi_color"],
                }
            return {
                "category": aq["us_aqi_category"],
                "color": aq["us_aqi_color"],
            }
        return {}
