"""Derived weather insight sensors (dew-point comfort, visibility, feels-like, pressure trend)."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.util.dt import utcnow

from ..const import (
    ATTRIBUTION_OPEN_METEO,
    DEW_POINT_COMFORT_OPTIONS,
    FEELS_LIKE_CONTEXT_OPTIONS,
    PRESSURE_TREND_OPTIONS,
    PRESSURE_TREND_SYMBOLS,
    VISIBILITY_CATEGORY_OPTIONS,
)
from ..coordinator import UnifiedCoordinator
from ..entity import AtmosBaseEntity, ForecastCurrentEntity, ForecastCurrentMixin
from ..insights import (
    classify_dew_point_comfort,
    classify_feels_like_context,
    classify_pressure_trend,
    classify_visibility,
)

if TYPE_CHECKING:
    from ..storage import StorageManager


@dataclass(frozen=True, kw_only=True)
class InsightSensorDescription(SensorEntityDescription):
    """Describe a derived insight sensor (enum type)."""

    compute_fn: Callable[[dict[str, Any]], str | None]
    options_list: list[str]
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


INSIGHT_SENSORS: tuple[InsightSensorDescription, ...] = (
    InsightSensorDescription(
        key="dew_point_comfort",
        translation_key="dew_point_comfort",
        device_class=SensorDeviceClass.ENUM,
        options_list=DEW_POINT_COMFORT_OPTIONS,
        compute_fn=lambda c: (
            classify_dew_point_comfort(c["dew_point"]).value
            if c.get("dew_point") is not None else None
        ),
        extra_attrs_fn=lambda c: {"dew_point_value": c.get("dew_point")},
    ),
    InsightSensorDescription(
        key="visibility_category",
        translation_key="visibility_category",
        device_class=SensorDeviceClass.ENUM,
        options_list=VISIBILITY_CATEGORY_OPTIONS,
        compute_fn=lambda c: (
            classify_visibility(c["visibility"]).value
            if c.get("visibility") is not None else None
        ),
        extra_attrs_fn=lambda c: {"visibility_km": c.get("visibility")},
    ),
    InsightSensorDescription(
        key="feels_like_context",
        translation_key="feels_like_context",
        device_class=SensorDeviceClass.ENUM,
        options_list=FEELS_LIKE_CONTEXT_OPTIONS,
        compute_fn=lambda c: (
            classify_feels_like_context(c["temperature"], c["apparent_temperature"]).value
            if c.get("temperature") is not None and c.get("apparent_temperature") is not None
            else None
        ),
        extra_attrs_fn=lambda c: {
            "temperature": c.get("temperature"),
            "apparent_temperature": c.get("apparent_temperature"),
            "difference": (
                round(c["apparent_temperature"] - c["temperature"], 1)
                if c.get("temperature") is not None and c.get("apparent_temperature") is not None
                else None
            ),
        },
    ),
)


class InsightSensor(ForecastCurrentEntity, SensorEntity):
    """Represent a derived weather insight sensor (enum type)."""

    entity_description: InsightSensorDescription

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        description: InsightSensorDescription,
        entry_id: str,
    ) -> None:
        """Initialize the InsightSensor."""
        super().__init__(coordinator, description, entry_id)
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = description.options_list

    @property
    def native_value(self) -> str | None:
        """Return the classified insight value."""
        current = self._current
        if not current:
            return None
        return self.entity_description.compute_fn(current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return input values used in the classification."""
        if self.entity_description.extra_attrs_fn is None:
            return {}
        current = self._current
        if not current:
            return {}
        return self.entity_description.extra_attrs_fn(current)


class PressureTrendSensor(ForecastCurrentMixin, AtmosBaseEntity, SensorEntity):
    """Represent the 3-hour pressure trend sensor."""

    _attr_translation_key = "pressure_trend"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PRESSURE_TREND_OPTIONS

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        entry_id: str,
        storage_manager: StorageManager,
        source_id: str,
    ) -> None:
        """Initialize the PressureTrendSensor."""
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_pressure_trend"
        self._storage = storage_manager
        self._source_id = source_id
        self._pressure_3h_ago: float | None = None
        # Track pending I/O so entry reload / HA shutdown can cancel it
        # rather than leaving an orphan task that might write after
        # StorageManager.async_flush has already snapshotted the state.
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._attr_attribution = ATTRIBUTION_OPEN_METEO

    def _schedule_save(self) -> None:
        """Fire-and-track an async pressure save."""
        task = self.hass.async_create_task(self._async_save_pressure())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def async_added_to_hass(self) -> None:
        """Register pressure history update on coordinator refresh."""
        await super().async_added_to_hass()
        if self.coordinator.data and self.coordinator.data.forecast:
            self._schedule_save()

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update, schedule async pressure save."""
        super()._handle_coordinator_update()
        self._schedule_save()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any in-flight pressure save before the entry is torn down.

        async_unload_entry calls StorageManager.async_flush to snapshot
        in-memory data to disk. Leaving a pressure save task running
        past that flush would let it overwrite the snapshot with a
        half-baked state after teardown.
        """
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()
        await super().async_will_remove_from_hass()

    async def _async_save_pressure(self) -> None:
        """Save current pressure and load 3h-ago value."""
        current = self._current
        if not current:
            return
        pressure = current.get("pressure")
        if pressure is None:
            return

        now = utcnow()
        config = self.coordinator.config
        # forecast_latitude/longitude are always resolved onto coordinator.config
        # by UnifiedCoordinator._resolve_config; 0.0 here never actually fires.
        await self._storage.save_pressure_reading(
            self._source_id, now, pressure,
            config.get("forecast_latitude", 0.0),
            config.get("forecast_longitude", 0.0),
        )
        self._pressure_3h_ago = await self._storage.load_pressure_3h_ago(
            self._source_id, now,
        )
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Return the pressure trend classification."""
        current = self._current
        if not current:
            return None
        pressure = current.get("pressure")
        if pressure is None:
            return None
        trend = classify_pressure_trend(pressure, self._pressure_3h_ago)
        return trend.value if trend is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return pressure values and trend symbol."""
        current = self._current
        if not current:
            return {}
        pressure = current.get("pressure")
        if pressure is None:
            return {}
        change = (
            round(pressure - self._pressure_3h_ago, 1)
            if self._pressure_3h_ago is not None else None
        )
        trend = classify_pressure_trend(pressure, self._pressure_3h_ago)
        return {
            "pressure_current": pressure,
            "pressure_3h_ago": self._pressure_3h_ago,
            "change_3h": change,
            "trend_symbol": PRESSURE_TREND_SYMBOLS.get(trend) if trend else None,
        }
