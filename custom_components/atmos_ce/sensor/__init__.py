"""Sensor platform for Atmos CE.

Public re-export surface, external callers (tests, HA platform loader)
use ``from custom_components.atmos_ce.sensor import X``. Symbols are
defined in the topic-specific submodules (forecast, astro, alerts,
stability, insights).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alerts import (
    ActiveAlertSensor,
    AlertCountSensor,
    UpcomingAlertSensor,
    _alert_attributes,
)
from .astro import ASTRO_SENSORS, AstroSensor, AstroSensorDescription
from .forecast import (
    AIR_QUALITY_SENSORS,
    FORECAST_SENSORS,
    WeatherForecastSensor,
    WeatherForecastSensorDescription,
)
from .insights import (
    INSIGHT_SENSORS,
    InsightSensor,
    InsightSensorDescription,
    PressureTrendSensor,
)
from .stability import (
    DERIVED_STABILITY_SENSORS,
    DerivedStabilitySensor,
    DerivedStabilitySensorDescription,
    StabilityAssessmentSensor,
)

if TYPE_CHECKING:
    from .. import AtmosCEConfigEntry

_LOGGER = logging.getLogger(__name__)

# Coordinator-based: no per-entity parallel updates needed.
# HA reads this attribute from the platform module.
PARALLEL_UPDATES = 0

__all__ = [
    "AIR_QUALITY_SENSORS",
    "ASTRO_SENSORS",
    "DERIVED_STABILITY_SENSORS",
    "FORECAST_SENSORS",
    "INSIGHT_SENSORS",
    "PARALLEL_UPDATES",
    "ActiveAlertSensor",
    "AlertCountSensor",
    "AstroSensor",
    "AstroSensorDescription",
    "DerivedStabilitySensor",
    "DerivedStabilitySensorDescription",
    "InsightSensor",
    "InsightSensorDescription",
    "PressureTrendSensor",
    "StabilityAssessmentSensor",
    "UpcomingAlertSensor",
    "WeatherForecastSensor",
    "WeatherForecastSensorDescription",
    "_alert_attributes",
    "async_setup_entry",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtmosCEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        return

    source_id = entry.runtime_data.source_id
    config = coordinator.config
    entry_id = entry.entry_id
    entities: list[SensorEntity] = []

    # Warning sensors, only if source has warning backend AND warnings enabled
    if coordinator.source.has_warning_backend and config.get("enable_warnings", True):
        entities.extend([
            ActiveAlertSensor(coordinator, source_id, entry_id),
            UpcomingAlertSensor(coordinator, source_id, entry_id),
            AlertCountSensor(coordinator, source_id, entry_id),
        ])

    # Forecast sensors, gated by enable_forecast toggle
    if config.get("enable_forecast", True):
        entities.extend(
            WeatherForecastSensor(coordinator, desc, entry_id)
            for desc in FORECAST_SENSORS
        )
        entities.extend(
            DerivedStabilitySensor(coordinator, desc, entry_id)
            for desc in DERIVED_STABILITY_SENSORS
        )
        entities.append(StabilityAssessmentSensor(coordinator, entry_id))
        entities.extend(
            InsightSensor(coordinator, desc, entry_id)
            for desc in INSIGHT_SENSORS
        )
        entities.append(
            PressureTrendSensor(
                coordinator, entry_id,
                entry.runtime_data.storage_manager,
                source_id,
            ),
        )

    # Air quality sensors, gated by enable_air_quality toggle
    if config.get("enable_air_quality", True):
        entities.extend(
            WeatherForecastSensor(coordinator, desc, entry_id)
            for desc in AIR_QUALITY_SENSORS
        )

    # Astro sensors, created if forecast OR AQ enabled
    if config.get("enable_forecast", True) or config.get("enable_air_quality", True):
        entities.extend(
            AstroSensor(coordinator, desc, entry_id)
            for desc in ASTRO_SENSORS
        )

    async_add_entities(entities)
    _LOGGER.debug("Added %d sensor entities for source: %s", len(entities), source_id)
