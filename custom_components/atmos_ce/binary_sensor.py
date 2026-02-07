"""Binary sensor platform for Atmos CE.

Creates one binary sensor per source indicating whether any
alerts are currently active.  Only created for sources with a
warning backend and warnings enabled.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import UnifiedCoordinator
from .entity import AtmosBaseEntity

if TYPE_CHECKING:
    from . import AtmosCEConfigEntry

_LOGGER = logging.getLogger(__name__)

# Coordinator-based: no per-entity parallel updates needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtmosCEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        return

    config = coordinator.config

    # Only create binary sensors for sources with warning backend + warnings enabled
    if not coordinator.source.has_warning_backend:
        return
    if not config.get("enable_warnings", True):
        return

    source_id = entry.runtime_data.source_id
    entry_id = entry.entry_id
    async_add_entities([AlertActiveBinarySensor(coordinator, source_id, entry_id)])
    _LOGGER.debug("Added 1 binary sensor entity for source: %s", source_id)


class AlertActiveBinarySensor(AtmosBaseEntity, BinarySensorEntity):
    """Binary sensor indicating if any alerts are active."""

    _attr_icon = "mdi:alert-circle"
    _attr_translation_key = "alert_active"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        source_id: str,
        entry_id: str,
    ) -> None:
        """Initialize the AlertActiveBinarySensor."""
        super().__init__(coordinator, entry_id)
        self.source_id = source_id
        self._attr_unique_id = f"{entry_id}_alert_active"
        self._attr_attribution = f"Data provided by {coordinator.source.source_name}"

    @property
    def is_on(self) -> bool:
        """Return true if any alerts are active."""
        data = self.coordinator.data
        return bool(data and data.alerts.active_alerts)
