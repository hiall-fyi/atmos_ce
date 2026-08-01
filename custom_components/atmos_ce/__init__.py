"""Atmos CE Integration for Home Assistant.

Comprehensive weather suite providing warnings, forecasts, air quality,
and astronomical data from multiple global sources.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DEFAULT_UPDATE_INTERVAL_MIN, DOMAIN
from .coordinator import UnifiedCoordinator
from .forecast_backend import OpenMeteoBackend
from .source_registry import get_source_by_id
from .storage import StorageManager

if TYPE_CHECKING:
    from homeassistant.util.json import JsonValueType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.WEATHER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _get_storage_manager(hass: HomeAssistant) -> StorageManager:
    """Return the shared StorageManager, creating it on first call.

    Args:
        hass: HomeAssistant instance.

    Returns:
        The shared StorageManager singleton.

    """
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    domain_data: dict[str, object] = hass.data[DOMAIN]
    if "storage_manager" not in domain_data:
        domain_data["storage_manager"] = StorageManager(hass)
    return domain_data["storage_manager"]


@dataclass(slots=True)
class AtmosCERuntimeData:
    """Runtime data stored on ConfigEntry.runtime_data."""

    coordinator: UnifiedCoordinator | None
    source_id: str
    storage_manager: StorageManager


type AtmosCEConfigEntry = ConfigEntry[AtmosCERuntimeData]


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    """Set up the Atmos CE domain (once per HA instance)."""
    storage_manager = _get_storage_manager(hass)

    async def _handle_stop(_event: Event) -> None:
        """Flush any pending debounced writes when HA is shutting down."""
        await storage_manager.async_flush()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _handle_stop)

    async def _handle_get_extended_forecast(call: ServiceCall) -> ServiceResponse:
        """Return extended hourly or daily forecast with all fields."""
        entry_id: str = call.data["config_entry_id"]
        forecast_type: str = call.data.get("type", "hourly")

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            msg = f"Config entry {entry_id} not found for {DOMAIN}"
            raise ServiceValidationError(msg)

        runtime_data: AtmosCERuntimeData = entry.runtime_data
        coordinator = runtime_data.coordinator
        if coordinator is None or coordinator.data is None:
            return {"forecast": []}

        forecast = coordinator.data.forecast
        if not forecast:
            return {"forecast": []}

        # The forecast lists are typed (DailyForecast / HourlyForecast)
        # but at runtime are plain dicts, JSON-safe for a ServiceResponse.
        # Cast at this typed→JSON boundary; mypy can't see a TypedDict as
        # a JsonValueType.
        if forecast_type == "daily":
            return {"forecast": cast("list[JsonValueType]", forecast.get("daily", []))}
        return {"forecast": cast("list[JsonValueType]", forecast.get("hourly", []))}

    hass.services.async_register(
        DOMAIN,
        "get_extended_forecast",
        _handle_get_extended_forecast,
        schema=vol.Schema({
            vol.Required("config_entry_id"): cv.string,
            vol.Optional("type", default="hourly"): vol.In(["hourly", "daily"]),
        }),
        supports_response=SupportsResponse.ONLY,
    )

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: AtmosCEConfigEntry,
) -> bool:
    """Set up Atmos CE from a config entry."""
    _LOGGER.debug("Setting up Atmos CE integration")

    source_id = entry.data.get("source_id")
    # Options take precedence over initial data.
    source_config: dict[str, object] = (
        dict(entry.options)
        if entry.options
        else dict(entry.data.get("source_config", {}))
    )

    if not source_id:
        _LOGGER.error("Config entry missing source_id")
        raise ConfigEntryNotReady("Config entry missing source_id")

    _LOGGER.debug("Setting up source: %s", source_id)

    source = get_source_by_id(source_id)
    if source is None:
        _LOGGER.error("Source %s not found", source_id)
        raise ConfigEntryNotReady(f"Source {source_id} not found")

    storage_manager = _get_storage_manager(hass)

    coordinator_config = dict(source_config)

    if not coordinator_config.get("enabled", True):
        _LOGGER.debug("Source %s is disabled, skipping setup", source_id)
        entry.runtime_data = AtmosCERuntimeData(
            coordinator=None,
            source_id=source_id,
            storage_manager=storage_manager,
        )
        return True

    update_interval = coordinator_config.get(
        "update_interval", DEFAULT_UPDATE_INTERVAL_MIN,
    )
    forecast_backend = OpenMeteoBackend()

    try:
        interval = timedelta(minutes=update_interval)
        coordinator = UnifiedCoordinator(
            hass, source, forecast_backend, coordinator_config,
            storage_manager, interval, config_entry=entry,
        )
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug("Successfully setup coordinator for %s", source.source_name)
    except (ConfigEntryAuthFailed, ConfigEntryNotReady):
        # HA reauth flow and "not ready" retry both rely on seeing the
        # original exception type, do not wrap them.
        raise
    except Exception as err:
        _LOGGER.exception(
            "Failed to setup coordinator for %s: %s", source.source_name, err,
        )
        raise ConfigEntryNotReady(
            f"Failed to setup coordinator for {source.source_name}: {err}",
        ) from err

    entry.runtime_data = AtmosCERuntimeData(
        coordinator=coordinator,
        source_id=source_id,
        storage_manager=storage_manager,
    )

    _LOGGER.debug("Successfully setup Atmos CE for %s", source.source_name)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AtmosCEConfigEntry,
) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Atmos CE integration")
    runtime_data = entry.runtime_data
    coordinator = runtime_data.coordinator

    # When the entry was set up with enabled=False the coordinator is None
    # and we never forwarded to the sensor/weather/binary_sensor platforms,
    # so we must not try to unload them either, async_unload_platforms
    # happens to return True in that case, but keeping setup/teardown
    # symmetrical avoids a foot-gun if HA ever tightens that contract.
    if coordinator is None:
        await runtime_data.storage_manager.async_flush()
        return True

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Stop the scheduled refresh so it does not keep firing for a
        # detached entry and producing ghost HTTP traffic.
        await coordinator.async_shutdown()
        # Flush any debounced pressure-history / last-fetch writes that may
        # still be within the _SAVE_DELAY window.
        await runtime_data.storage_manager.async_flush()
        _LOGGER.debug("Stopped coordinator for %s", runtime_data.source_id)
    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: AtmosCEConfigEntry,
) -> None:
    """Purge a removed entry's persisted data from the shared store.

    Runs after the entry is unloaded, so ``runtime_data`` is gone: the
    source_id comes from ``entry.data`` and the storage manager from the
    domain singleton.
    """
    source_id = entry.data.get("source_id")
    if not source_id:
        return
    storage_manager = _get_storage_manager(hass)
    await storage_manager.async_remove_source(source_id)
    _LOGGER.debug("Purged stored data for removed entry %s", source_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: AtmosCEConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removal of stale devices.

    Args:
        hass: HomeAssistant instance.
        config_entry: The config entry owning the device.
        device_entry: The device entry to be removed.

    Returns:
        True if the device can be removed.

    """
    return True
