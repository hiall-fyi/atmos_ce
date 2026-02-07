"""Storage manager for Atmos CE.

This module handles persistent data storage for the integration:
last-fetch timestamps used by diagnostics, and pressure history
used by the pressure trend sensor.
Uses Home Assistant's Store helper for atomic writes, versioning,
and proper async handling.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime, timedelta
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import PRESSURE_HISTORY_RETENTION_H, PRESSURE_TREND_WINDOW_H

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "atmos_ce"
STORAGE_VERSION = 1

# Delay (seconds) before flushing in-memory changes to disk.
# Multiple rapid writes within this window are coalesced into one I/O.
_SAVE_DELAY: Final = 5


class StorageManager:
    """Manage persistent storage for the integration.

    Uses Home Assistant's Store helper which provides atomic writes,
    versioning, and migration support out of the box.  An asyncio.Lock
    serialises all read-modify-write operations to prevent concurrent
    coordinators from corrupting the shared data dict.

    Writes are debounced via ``Store.async_delay_save`` so that
    multiple coordinator updates within ``_SAVE_DELAY`` seconds are
    coalesced into a single disk write.

    The in-memory ``_data`` cache is authoritative and loaded once per
    process: it is read from disk on first access and never reloaded.
    HA is the single writer of this file, so external edits made while
    HA is running are silently overwritten on the next flush, this is
    intentional (the integration owns the file), not a sync gap.

    Storage structure (single file at .storage/atmos_ce):
        {
            "last_fetch": { "<source_id>": {...} },
            "pressure_history": { "<source_id>": [...] }
        }
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the StorageManager."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY,
        )
        self._data: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def _async_get_data(self) -> dict[str, Any]:
        """Load data from store, initialising empty structure if needed.

        Returns:
            The full storage dictionary.

        """
        if self._data is None:
            stored = await self._store.async_load()
            if stored is None:
                stored = {}
            self._data = {
                "last_fetch": stored.get("last_fetch", {}),
                "pressure_history": stored.get("pressure_history", {}),
            }
        return self._data

    def _schedule_save(self) -> None:
        """Schedule a debounced write of in-memory data to disk."""
        if self._data is not None:
            self._store.async_delay_save(lambda: copy.deepcopy(self._data), _SAVE_DELAY)

    async def async_flush(self) -> None:
        """Flush any pending debounced save to disk immediately.

        Call this on HA shutdown or entry unload to avoid losing the last
        pressure reading / last-fetch timestamp when the debounce window
        has not yet elapsed.
        """
        if self._data is None:
            return
        await self._store.async_save(copy.deepcopy(self._data))
        _LOGGER.debug("Flushed pending storage writes to disk")

    async def async_remove_source(self, source_id: str) -> None:
        """Delete a source's persisted data and flush immediately.

        Keeps a removed source's last-fetch record and pressure history
        from orphaning in the shared store, and stops a re-added source
        from reusing pressure readings taken before the removal.

        Args:
            source_id: Source identifier whose data should be purged.

        """
        async with self._lock:
            data = await self._async_get_data()
            removed = False
            for bucket in ("last_fetch", "pressure_history"):
                if source_id in data.get(bucket, {}):
                    del data[bucket][source_id]
                    removed = True
            if not removed:
                return
            # Flush synchronously rather than debounce: the entry is gone,
            # so there is no later cycle to coalesce the write with.
            await self._store.async_save(copy.deepcopy(self._data))
            _LOGGER.debug("Removed stored data for source %s", source_id)

    # ------------------------------------------------------------------
    # Last fetch
    # ------------------------------------------------------------------

    async def save_last_fetch(
        self,
        source_id: str,
        timestamp: datetime,
        success: bool = True,
        alert_count: int = 0,
    ) -> None:
        """Save last fetch timestamp for a source.

        Args:
            source_id: Source identifier.
            timestamp: Fetch timestamp.
            success: Whether the fetch was successful.
            alert_count: Number of alerts fetched.

        Raises:
            Exception: If saving fails (propagated to caller).

        """
        async with self._lock:
            data = await self._async_get_data()
            data["last_fetch"][source_id] = {
                "timestamp": timestamp.isoformat(),
                "success": success,
                "alert_count": alert_count,
            }
            self._schedule_save()
            _LOGGER.debug(
                "Saved last fetch timestamp for source %s: %s",
                source_id,
                timestamp.isoformat(),
            )

    async def load_last_fetch(self, source_id: str) -> dict[str, Any] | None:
        """Load last fetch information for a source.

        Args:
            source_id: Source identifier.

        Returns:
            Dictionary with timestamp, success, and alert_count, or None.

        """
        async with self._lock:
            try:
                data = await self._async_get_data()
                fetch_data = data["last_fetch"].get(source_id)
                if fetch_data:
                    _LOGGER.debug(
                        "Loaded last fetch for source %s: %s",
                        source_id,
                        fetch_data.get("timestamp"),
                    )
                else:
                    _LOGGER.debug(
                        "No last fetch data found for source %s", source_id,
                    )
                return fetch_data
            except Exception:
                _LOGGER.exception(
                    "Failed to load last fetch for source %s",
                    source_id,
                )
                return None

    # ------------------------------------------------------------------
    # Pressure history
    # ------------------------------------------------------------------

    async def save_pressure_reading(
        self,
        source_id: str,
        timestamp: datetime,
        pressure_hpa: float,
    ) -> None:
        """Save a pressure reading and prune old entries.

        Args:
            source_id: Source identifier.
            timestamp: Reading timestamp.
            pressure_hpa: Pressure in hPa.

        """
        async with self._lock:
            data = await self._async_get_data()
            history = data.setdefault("pressure_history", {})
            source_history: list[dict[str, Any]] = history.setdefault(source_id, [])

            # Round timestamp to nearest minute
            ts_key = timestamp.replace(second=0, microsecond=0).isoformat()

            # Dedup: update existing entry or append new
            existing = next(
                (e for e in source_history if e["timestamp"] == ts_key), None,
            )
            if existing is not None:
                existing["pressure"] = pressure_hpa
                log_action = "Updated"
            else:
                source_history.append({"timestamp": ts_key, "pressure": pressure_hpa})
                log_action = "Saved"

            # Prune entries older than retention window
            cutoff = (
                timestamp - timedelta(hours=PRESSURE_HISTORY_RETENTION_H)
            ).isoformat()
            history[source_id] = [
                e for e in source_history if e["timestamp"] >= cutoff
            ]

            self._schedule_save()
            _LOGGER.debug(
                "%s pressure reading for source %s: %.1f hPa at %s",
                log_action,
                source_id,
                pressure_hpa,
                ts_key,
            )

    async def load_pressure_3h_ago(
        self,
        source_id: str,
        now: datetime,
    ) -> float | None:
        """Load the pressure reading closest to 3 hours ago.

        Returns None if no reading within ±30 minutes of the 3h mark.

        Args:
            source_id: Source identifier.
            now: Current timestamp.

        Returns:
            Pressure in hPa, or None.

        """
        async with self._lock:
            data = await self._async_get_data()
            # Snapshot inside the lock: data["pressure_history"][source_id]
            # is a live reference that a concurrent save_pressure_reading
            # may replace mid-iteration.
            history: list[dict[str, Any]] = list(
                data.get("pressure_history", {}).get(source_id, []),
            )

        if not history:
            return None

        target = (now - timedelta(hours=PRESSURE_TREND_WINDOW_H)).timestamp()
        best: float | None = None
        best_diff = float("inf")

        for entry in history:
            try:
                entry_ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                diff = abs(entry_ts - target)
                if diff < best_diff:
                    best_diff = diff
                    best = entry["pressure"]
            except (ValueError, KeyError):
                continue

        # Only return if within ±30 minutes of target
        if best is not None and best_diff <= 1800:
            return best
        return None

    async def load_pressure_history_metadata(
        self, source_id: str,
    ) -> dict[str, Any]:
        """Load pressure history metadata (count and time range).

        Returns entry count and oldest/newest timestamps without
        exposing raw pressure values.

        Args:
            source_id: Source identifier.

        Returns:
            Dict with entry_count, oldest_entry, newest_entry.

        """
        async with self._lock:
            data = await self._async_get_data()
            # Snapshot inside the lock to avoid racing save_pressure_reading,
            # which rebinds data["pressure_history"][source_id] to a new list.
            history: list[dict[str, Any]] = list(
                data.get("pressure_history", {}).get(source_id, []),
            )

        if not history:
            return {"entry_count": 0, "oldest_entry": None, "newest_entry": None}

        timestamps = [e["timestamp"] for e in history if isinstance(e.get("timestamp"), str)]
        if not timestamps:
            return {"entry_count": 0, "oldest_entry": None, "newest_entry": None}

        return {
            "entry_count": len(timestamps),
            "oldest_entry": min(timestamps),
            "newest_entry": max(timestamps),
        }
