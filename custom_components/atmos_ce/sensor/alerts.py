"""Alert-based sensor entities (active / upcoming / count)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory

from ..coordinator import UnifiedCoordinator
from ..entity import AtmosBaseEntity
from ..helpers import calculate_progress, seconds_until
from ..models import Alert

# Sentinel values surfaced when there's no alert. Declared once so it
# never drifts from Alert's field set.
_ALERT_NULL_ATTRS: dict[str, Any] = {
    "alert_type": None,
    "severity": None,
    "level": None,
    "start_time": None,
    "end_time": None,
    "locations": (),
    "summary": None,
    "description": None,
    "link": None,
    "source": None,
    "icon": None,
    "color": None,
    "progress": 0.0,
    "time_until_start": 0,
    "time_until_end": 0,
}


def _alert_attributes(alert: Alert | None) -> dict[str, Any]:
    """Build extra-state-attributes dict for an alert (or empty sentinel).

    Derives the field set from ``Alert`` via ``dataclasses.asdict`` so new
    fields on the dataclass surface automatically, no hand-maintained
    two-branch duplication.
    """
    if alert is None:
        return dict(_ALERT_NULL_ATTRS)
    attrs = asdict(alert)
    attrs.pop("alert_id", None)  # not surfaced as state attribute
    attrs["progress"] = calculate_progress(alert.start_time, alert.end_time)
    attrs["time_until_start"] = seconds_until(alert.start_time)
    attrs["time_until_end"] = seconds_until(alert.end_time)
    return attrs


def _alert_list_attributes(
    active: list[Alert], upcoming: list[Alert],
) -> list[dict[str, Any]]:
    """Build the ``all_alerts`` attribute: active first, then upcoming.

    Each element is ``_alert_attributes(alert)`` plus an ``active`` flag.
    Active and upcoming are already severity-first ordered by the
    coordinator; this preserves that order and tags each element. There can
    be multiple active alerts simultaneously — every one is listed flat
    (no merge, no hiding).
    """
    return [
        {**_alert_attributes(alert), "active": True} for alert in active
    ] + [
        {**_alert_attributes(alert), "active": False} for alert in upcoming
    ]


class _BaseAlertSensor(AtmosBaseEntity, SensorEntity):
    """Base class for alert sensors with shared initialisation logic."""

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        source_id: str,
        entry_id: str,
        *,
        translation_key: str,
    ) -> None:
        """Initialize the _BaseAlertSensor."""
        super().__init__(coordinator, entry_id)
        self.source_id = source_id
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry_id}_{translation_key}"
        self._attr_attribution = f"Data provided by {coordinator.source.source_name}"


class ActiveAlertSensor(_BaseAlertSensor):
    """Sensor showing the current highest-priority active alert."""

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        source_id: str,
        entry_id: str,
    ) -> None:
        """Initialize the ActiveAlertSensor."""
        super().__init__(
            coordinator, source_id, entry_id,
            translation_key="active_alert",
        )

    @property
    def _active_alerts(self) -> list[Alert]:
        """Return active alerts from coordinator data."""
        data = self.coordinator.data
        return data.alerts.active_alerts if data else []

    @property
    def icon(self) -> str:
        """Return dynamic icon based on active alert type."""
        active = self._active_alerts
        return active[0].icon if active and active[0].icon else "mdi:alert"

    @property
    def native_value(self) -> str:
        """Return alert summary or 'None' when no alerts are active."""
        active = self._active_alerts
        return active[0].summary if active else "None"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return alert detail attributes plus the full alert list."""
        data = self.coordinator.data
        active = data.alerts.active_alerts if data else []
        upcoming = data.alerts.upcoming_alerts if data else []
        attrs = _alert_attributes(active[0] if active else None)
        attrs["all_alerts"] = _alert_list_attributes(active, upcoming)
        return attrs


class UpcomingAlertSensor(_BaseAlertSensor):
    """Sensor showing the next upcoming alert."""

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        source_id: str,
        entry_id: str,
    ) -> None:
        """Initialize the UpcomingAlertSensor."""
        super().__init__(
            coordinator, source_id, entry_id,
            translation_key="upcoming_alert",
        )

    @property
    def _upcoming_alerts(self) -> list[Alert]:
        """Return upcoming alerts from coordinator data."""
        data = self.coordinator.data
        return data.alerts.upcoming_alerts if data else []

    @property
    def icon(self) -> str:
        """Return dynamic icon based on upcoming alert type."""
        upcoming = self._upcoming_alerts
        return upcoming[0].icon if upcoming and upcoming[0].icon else "mdi:clock-alert"

    @property
    def native_value(self) -> str:
        """Return alert summary or 'None' when no alerts are upcoming."""
        upcoming = self._upcoming_alerts
        return upcoming[0].summary if upcoming else "None"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return alert detail attributes."""
        upcoming = self._upcoming_alerts
        attrs = _alert_attributes(upcoming[0] if upcoming else None)
        if upcoming:
            attrs["progress"] = 0.0
        return attrs


class AlertCountSensor(_BaseAlertSensor):
    """Sensor showing the number of active alerts."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        source_id: str,
        entry_id: str,
    ) -> None:
        """Initialize the AlertCountSensor."""
        super().__init__(
            coordinator, source_id, entry_id,
            translation_key="alert_count",
        )
        self._attr_native_unit_of_measurement = "alerts"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        """Return the number of active alerts."""
        data = self.coordinator.data
        return len(data.alerts.active_alerts) if data else 0
