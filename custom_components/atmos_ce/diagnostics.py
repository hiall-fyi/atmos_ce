"""Diagnostics support for Atmos CE."""
from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AtmosCEConfigEntry

TO_REDACT = {
    "api_key",
    "latitude",
    "longitude",
    "forecast_latitude",
    "forecast_longitude",
    "location_name",
    "locations",
    # User-entered geographic selectors, reveal where the user lives.
    "location_filters",
    "counties",
    "provinces",
    "state",
    # Alert free-text fields, may embed location names, region IDs,
    # query-string user tokens, or PII lifted from upstream bulletins.
    "description",
    "link",
    "summary",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: AtmosCEConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    storage_manager = entry.runtime_data.storage_manager
    source_id = entry.runtime_data.source_id

    diag: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
    }

    if coordinator is not None:
        diag["coordinator"] = {
            "source_id": source_id,
            "has_warning_backend": coordinator.source.has_warning_backend,
            "last_update_success": coordinator.last_update_success,
            "last_exception": (
                repr(coordinator.last_exception)
                if coordinator.last_exception
                else None
            ),
        }

        data = coordinator.data
        if data is not None:
            # Alert diagnostics
            all_alerts = data.alerts.all_alerts
            diag["alerts"] = {
                "count": len(all_alerts),
                "items": [
                    async_redact_data(
                        {**dataclasses.asdict(a), "locations": list(a.locations)},
                        TO_REDACT,
                    )
                    for a in all_alerts
                ],
            }

            # Forecast diagnostics
            forecast = data.forecast
            diag["forecast"] = {
                "has_current": forecast is not None and "current" in forecast,
                "hourly_count": len(forecast.get("hourly", [])) if forecast else 0,
                "daily_count": len(forecast.get("daily", [])) if forecast else 0,
                "has_air_quality": data.air_quality is not None,
            }
    else:
        diag["coordinator"] = {
            "source_id": source_id,
            "status": "disabled_at_setup",
        }

    # Storage diagnostics
    last_fetch = await storage_manager.load_last_fetch(source_id)
    pressure_meta = await storage_manager.load_pressure_history_metadata(source_id)
    diag["storage"] = {
        "last_fetch": last_fetch,
        "pressure_history": pressure_meta,
    }

    return diag
