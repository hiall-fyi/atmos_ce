"""Derived stability sensor entities (wind shear, lapse rate, LCL, composite)."""
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

from ..const import (
    STABILITY_TIER_ICONS,
    STABILITY_TIER_LABELS,
    STABILITY_TIER_OPTIONS,
)
from ..coordinator import UnifiedCoordinator
from ..entity import AtmosBaseEntity, ForecastCurrentEntity, ForecastCurrentMixin
from ..stability import (
    StabilityAssessment,
    compute_lapse_rate,
    compute_lcl_height,
    compute_stability_assessment,
    compute_wind_shear,
)


@dataclass(frozen=True, kw_only=True)
class DerivedStabilitySensorDescription(SensorEntityDescription):
    """Describe a derived stability sensor computed from multiple fields."""

    compute_fn: Callable[[dict[str, Any]], float | int | None]
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


DERIVED_STABILITY_SENSORS: tuple[DerivedStabilitySensorDescription, ...] = (
    DerivedStabilitySensorDescription(
        key="wind_shear_0_6km",
        translation_key="wind_shear_0_6km",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="km/h",
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        compute_fn=lambda c: compute_wind_shear(
            c.get("wind_speed"), c.get("wind_direction"),
            c.get("wind_speed_500hpa"), c.get("wind_direction_500hpa"),
        ),
        extra_attrs_fn=lambda c: {
            "surface_wind_speed": c.get("wind_speed"),
            "surface_wind_direction": c.get("wind_direction"),
            "wind_speed_500hpa": c.get("wind_speed_500hpa"),
            "wind_direction_500hpa": c.get("wind_direction_500hpa"),
        },
    ),
    DerivedStabilitySensorDescription(
        key="lapse_rate_700_500",
        translation_key="lapse_rate_700_500",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="°C/km",
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        compute_fn=lambda c: compute_lapse_rate(
            c.get("temperature_700hpa"), c.get("temperature_500hpa"),
            c.get("geopotential_height_700hpa"),
            c.get("geopotential_height_500hpa"),
        ),
        extra_attrs_fn=lambda c: {
            "temperature_700hpa": c.get("temperature_700hpa"),
            "temperature_500hpa": c.get("temperature_500hpa"),
            "height_700hpa": c.get("geopotential_height_700hpa"),
            "height_500hpa": c.get("geopotential_height_500hpa"),
        },
    ),
    DerivedStabilitySensorDescription(
        key="lcl_height",
        translation_key="lcl_height",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="m",
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        compute_fn=lambda c: compute_lcl_height(
            c.get("temperature"), c.get("dew_point"),
        ),
        extra_attrs_fn=lambda c: {
            "surface_temperature": c.get("temperature"),
            "dew_point": c.get("dew_point"),
        },
    ),
)


class DerivedStabilitySensor(ForecastCurrentEntity, SensorEntity):
    """Represent a derived atmospheric stability sensor."""

    entity_description: DerivedStabilitySensorDescription
    _attribution_template = "Derived from {source} data"

    @property
    def native_value(self) -> float | int | None:
        """Return the computed sensor value from coordinator data."""
        current = self._current
        if not current:
            return None
        return self.entity_description.compute_fn(current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return input values used in the computation."""
        if self.entity_description.extra_attrs_fn is None:
            return {}
        current = self._current
        if not current:
            return {}
        return self.entity_description.extra_attrs_fn(current)


class StabilityAssessmentSensor(ForecastCurrentMixin, AtmosBaseEntity, SensorEntity):
    """Represent the composite atmospheric stability assessment."""

    _attr_translation_key = "stability_assessment"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STABILITY_TIER_OPTIONS

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        entry_id: str,
    ) -> None:
        """Initialize the StabilityAssessmentSensor."""
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_stability_assessment"
        self._attr_attribution = (
            f"Derived from {coordinator.source.source_name} data"
        )

    def _get_assessment(self) -> StabilityAssessment | None:
        """Compute the stability assessment from current conditions."""
        current = self._current
        if not current:
            return None
        # .get(): the test suite exercises this path with partial current
        # dicts (missing pressure-level keys) to verify missing-parameter
        # handling, so indexing would KeyError. The compute_* helpers
        # already treat None as "parameter absent".
        wind_shear = compute_wind_shear(
            current.get("wind_speed"), current.get("wind_direction"),
            current.get("wind_speed_500hpa"), current.get("wind_direction_500hpa"),
        )
        lapse_rate = compute_lapse_rate(
            current.get("temperature_700hpa"), current.get("temperature_500hpa"),
            current.get("geopotential_height_700hpa"),
            current.get("geopotential_height_500hpa"),
        )
        return compute_stability_assessment(
            cape=current.get("cape"),
            lifted_index=current.get("lifted_index"),
            wind_shear=wind_shear,
            lapse_rate=lapse_rate,
        )

    @property
    def native_value(self) -> str | None:
        """Return the composite tier label."""
        assessment = self._get_assessment()
        return assessment.tier_label if assessment else None

    @property
    def icon(self) -> str:
        """Return dynamic icon based on the current stability tier."""
        assessment = self._get_assessment()
        if assessment is None:
            return "mdi:weather-sunny"
        return STABILITY_TIER_ICONS.get(
            assessment.tier, "mdi:weather-sunny",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-parameter tiers, values, and confidence."""
        assessment = self._get_assessment()
        if assessment is None:
            return {}
        return {
            "cape_tier": STABILITY_TIER_LABELS.get(assessment.cape_tier)
                if assessment.cape_tier is not None else None,
            "lifted_index_tier": STABILITY_TIER_LABELS.get(assessment.lifted_index_tier)
                if assessment.lifted_index_tier is not None else None,
            "wind_shear_tier": STABILITY_TIER_LABELS.get(assessment.wind_shear_tier)
                if assessment.wind_shear_tier is not None else None,
            "lapse_rate_tier": STABILITY_TIER_LABELS.get(assessment.lapse_rate_tier)
                if assessment.lapse_rate_tier is not None else None,
            "cape_value": assessment.cape_value,
            "lifted_index_value": assessment.lifted_index_value,
            "wind_shear_value": assessment.wind_shear_value,
            "lapse_rate_value": assessment.lapse_rate_value,
            "parameters_available": assessment.parameters_available,
            "parameters_total": assessment.parameters_total,
            "assessment_confidence": assessment.confidence,
        }
