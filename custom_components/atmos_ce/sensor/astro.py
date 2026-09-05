"""Astronomical sensor entities (sun/moon timestamps, moon phase, daylight)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime

from ..astro import MOON_PHASES
from ..entity import AtmosDescriptionEntity


@dataclass(frozen=True, kw_only=True)
class AstroSensorDescription(SensorEntityDescription):
    """Describe an astronomical sensor with its data key in the astro dict."""

    data_key: str


ASTRO_SENSORS: tuple[AstroSensorDescription, ...] = (
    AstroSensorDescription(
        key="golden_hour_morning_start", translation_key="golden_hour_morning_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="golden_hour_morning_start",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="golden_hour_morning_end", translation_key="golden_hour_morning_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="golden_hour_morning_end",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="golden_hour_evening_start", translation_key="golden_hour_evening_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="golden_hour_evening_start",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="golden_hour_evening_end", translation_key="golden_hour_evening_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="golden_hour_evening_end",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="blue_hour_morning_start", translation_key="blue_hour_morning_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="blue_hour_morning_start",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="blue_hour_morning_end", translation_key="blue_hour_morning_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="blue_hour_morning_end",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="blue_hour_evening_start", translation_key="blue_hour_evening_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="blue_hour_evening_start",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="blue_hour_evening_end", translation_key="blue_hour_evening_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="blue_hour_evening_end",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="moon_phase", translation_key="moon_phase",
        device_class=SensorDeviceClass.ENUM,
        options=list(MOON_PHASES),
        data_key="phase_name",
    ),
    AstroSensorDescription(
        key="moonrise", translation_key="moonrise",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="moonrise",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="moonset", translation_key="moonset",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_key="moonset",
        entity_registry_enabled_default=False,
    ),
    AstroSensorDescription(
        key="daylight_duration", translation_key="daylight_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="daylight_duration",
    ),
)


class AstroSensor(AtmosDescriptionEntity, SensorEntity):
    """Represent an astronomical sensor (sun/moon data)."""

    entity_description: AstroSensorDescription
    _attr_attribution = "Calculated from NOAA/Meeus algorithms"

    @property
    def available(self) -> bool:
        """Return True when astronomical data has been computed."""
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data
        return data is not None and bool(data.astro)

    @property
    def native_value(self) -> datetime | str | float | None:
        """Return the sensor value from coordinator astro data.

        Timestamp sensors (moonrise, moonset, golden/blue hour) return
        a datetime object directly, HA requires this for
        ``SensorDeviceClass.TIMESTAMP`` (not an ISO string).
        """
        data = self.coordinator.data
        if not data:
            return None
        astro = data.astro
        if not astro:
            return None
        value = astro.get(self.entity_description.data_key)
        if value is None:
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for moon phase sensor."""
        if self.entity_description.key != "moon_phase":
            return {}
        data = self.coordinator.data
        if not data:
            return {}
        astro = data.astro
        if not astro:
            return {}
        return {
            "illumination": astro.get("illumination"),
            "moon_age": astro.get("moon_age"),
        }
