"""Shared coordinator-entity base classes for Atmos CE.

Centralises the per-entity boilerplate every platform repeated by hand:
unique_id derivation, device info, attribution, and the
``forecast.current`` availability guard. Defining it once keeps the
entity classes to just their value/attribute logic and stops the guard
bodies from drifting apart as new sensors are added.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .helpers import build_device_info

if TYPE_CHECKING:
    from homeassistant.helpers.entity import EntityDescription

    from .coordinator import UnifiedCoordinator
    from .forecast_types import CurrentConditions


class AtmosBaseEntity(CoordinatorEntity["UnifiedCoordinator"]):
    """Base for every Atmos CE entity sharing one source device.

    Sets the shared device info so subclasses only declare their own
    unique_id, name, and value logic.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        entry_id: str,
    ) -> None:
        """Initialize the AtmosBaseEntity."""
        super().__init__(coordinator)
        self._attr_device_info = build_device_info(coordinator, entry_id)


class AtmosDescriptionEntity(AtmosBaseEntity):
    """Base for description-driven Atmos CE sensors.

    Derives unique_id from ``entry_id`` + the description key and sets a
    source-derived attribution. Subclasses set ``entity_description`` via
    the constructor and add only their ``native_value`` /
    ``extra_state_attributes`` logic.

    The attribution template is overridable via the ``_attribution_template``
    class attribute (``"{source}"`` is substituted with the source name)
    so forecast sensors read "Data provided by X" while derived sensors
    read "Derived from X data" without re-implementing __init__.
    """

    _attribution_template = "Data provided by {source}"

    def __init__(
        self,
        coordinator: UnifiedCoordinator,
        description: EntityDescription,
        entry_id: str,
    ) -> None:
        """Initialize the AtmosDescriptionEntity."""
        super().__init__(coordinator, entry_id)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_attribution = self._attribution_template.format(
            source=coordinator.source.source_name,
        )


class ForecastCurrentMixin(CoordinatorEntity["UnifiedCoordinator"]):
    """Shared ``forecast.current`` availability guard and accessor.

    Mixed into both description-driven sensors and the bespoke
    PressureTrendSensor so every consumer of the current-conditions block
    reads it the same way instead of repeating the None-walk.
    """

    @property
    def available(self) -> bool:
        """Return True when the current-conditions block is present."""
        if not self.coordinator.last_update_success:
            return False
        return self._current is not None

    @property
    def _current(self) -> CurrentConditions | None:
        """Return the current-conditions dict, or None when unavailable."""
        data = self.coordinator.data
        if data is None or data.forecast is None:
            return None
        return data.forecast.get("current")


class ForecastCurrentEntity(ForecastCurrentMixin, AtmosDescriptionEntity):
    """Description-driven sensor backed by the ``forecast.current`` block."""
