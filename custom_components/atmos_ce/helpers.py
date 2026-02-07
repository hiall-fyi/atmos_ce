"""Shared helpers for Atmos CE.

Centralises DeviceInfo construction, shared time utilities, and
alert filtering to eliminate duplication across sensor, binary_sensor,
and weather platforms.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util.dt import utcnow

if TYPE_CHECKING:
    from .coordinator import UnifiedCoordinator

from .const import DOMAIN
from .models import Alert

_LOGGER = logging.getLogger(__name__)


class CoordinatorConfig(TypedDict, total=False):
    """Known keys in coordinator config dicts."""

    latitude: float
    longitude: float
    location_name: str
    enabled: bool
    update_interval: int
    forecast_latitude: float
    forecast_longitude: float
    source_id: str
    enable_warnings: bool
    enable_forecast: bool
    enable_air_quality: bool


# ---------------------------------------------------------------------------
# DeviceInfo builders
# ---------------------------------------------------------------------------


def get_device_info(
    entry_id: str,
    source_name: str,
    config: CoordinatorConfig,
    hass_latitude: float,
    hass_longitude: float,
) -> DeviceInfo:
    """Build DeviceInfo for a unified source device.

    All entities from a single config entry share this device.

    Args:
        entry_id: Config entry ID for stable device identity.
        source_name: Human-readable source name.
        config: Coordinator config dict.
        hass_latitude: Home Assistant configured latitude.
        hass_longitude: Home Assistant configured longitude.

    Returns:
        DeviceInfo instance.

    """
    latitude = config.get("forecast_latitude", hass_latitude)
    longitude = config.get("forecast_longitude", hass_longitude)

    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=source_name,
        manufacturer="Atmos CE",
        model=f"{source_name} Weather",
        configuration_url=f"https://www.google.com/maps?q={latitude},{longitude}",
    )


def build_device_info(
    coordinator: UnifiedCoordinator,
    entry_id: str,
) -> DeviceInfo:
    """Build DeviceInfo from a coordinator and entry ID.

    Convenience wrapper around ``get_device_info`` that extracts
    the required parameters from the coordinator.

    Args:
        coordinator: The UnifiedCoordinator instance.
        entry_id: Config entry ID for stable device identity.

    Returns:
        DeviceInfo instance.

    """
    return get_device_info(
        entry_id,
        coordinator.source.source_name,
        coordinator.config,
        coordinator.hass.config.latitude,
        coordinator.hass.config.longitude,
    )


# ---------------------------------------------------------------------------
# Shared time utilities
# ---------------------------------------------------------------------------


def calculate_progress(start_str: str, end_str: str) -> float:
    """Calculate alert progress as percentage elapsed (0–100).

    Returns 0.0 if ``end_str`` is empty (no expiry / "until further notice").

    Args:
        start_str: ISO 8601 start time.
        end_str: ISO 8601 end time (empty string = no expiry).

    Returns:
        Percentage elapsed, clamped to 0–100.

    """
    if not end_str:
        return 0.0
    try:
        now = utcnow()
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        total = (end - start).total_seconds()
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, (now - start).total_seconds() / total * 100))
    except (ValueError, AttributeError) as err:
        _LOGGER.warning("Error calculating progress: %s", err)
        return 0.0


def seconds_until(time_str: str) -> int:
    """Calculate seconds from now until *time_str*.

    Returns a large sentinel (999 999) if ``time_str`` is empty,
    indicating no defined end time.

    Args:
        time_str: ISO 8601 datetime string (empty = no end time).

    Returns:
        Seconds until the given time (negative if in the past).

    """
    if not time_str:
        return 999_999
    try:
        return int(
            (datetime.fromisoformat(time_str) - utcnow()).total_seconds(),
        )
    except (ValueError, AttributeError) as err:
        _LOGGER.warning("Error calculating seconds_until: %s", err)
        return 0


# ---------------------------------------------------------------------------
# Shared alert filtering
# ---------------------------------------------------------------------------


def _parse_iso_to_utc(value: str) -> datetime | None:
    """Parse an ISO-8601 datetime and normalise to UTC.

    Used as a sort key so alerts from sources with different UTC offsets
    order by their real instant in time instead of the raw ISO string
    (which would put "10:00-02:00" before "11:00+00:00" even though they
    represent the same UTC moment).

    Args:
        value: ISO-8601 datetime string, possibly naive.

    Returns:
        tz-aware UTC datetime, or None if the input is empty/malformed.

    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_active_alerts(data: list[Alert] | None) -> list[Alert]:
    """Return currently-active alerts sorted by priority.

    Alerts with an empty ``end_time`` are treated as having no expiry
    ("until further notice") and are always considered active if their
    start time is in the past.

    Args:
        data: List of Alert objects (or None).

    Returns:
        Active alerts sorted by level (desc) then start_time (asc).

    """
    if not data:
        return []
    now = utcnow()
    active: list[Alert] = []
    for alert in data:
        # Normalise to UTC so a naive timestamp doesn't crash the
        # comparison against the tz-aware now and drop the whole list.
        start = _parse_iso_to_utc(alert.start_time)
        if start is None:
            _LOGGER.warning(
                "Skipping alert with unparseable start_time: %r",
                alert.start_time,
            )
            continue
        if not alert.end_time:
            # No end time = active if started.
            if start <= now:
                active.append(alert)
            continue
        end = _parse_iso_to_utc(alert.end_time)
        if end is None:
            # Malformed end time: treat as "until further notice".
            if start <= now:
                active.append(alert)
            continue
        if start <= now < end:
            active.append(alert)
    # Sort by UTC-normalised datetime so mixed TZ offsets order by their
    # real instant, not the raw ISO string. Unparseable timestamps sort
    # to the end within the same level.
    _min_utc = datetime.min.replace(tzinfo=UTC)
    active.sort(
        key=lambda a: (-a.level, _parse_iso_to_utc(a.start_time) or _min_utc),
    )
    return active


def get_upcoming_alerts(data: list[Alert] | None) -> list[Alert]:
    """Return future alerts sorted by start time.

    Alerts with an empty ``end_time`` are included if their start time
    is in the future (they will move to active once started).

    Args:
        data: List of Alert objects (or None).

    Returns:
        Upcoming alerts sorted by start_time (asc).

    """
    if not data:
        return []
    now = utcnow()
    upcoming: list[Alert] = []
    for alert in data:
        # Normalise to UTC (see get_active_alerts) so a naive timestamp
        # doesn't abort the loop.
        start = _parse_iso_to_utc(alert.start_time)
        if start is None:
            _LOGGER.warning(
                "Skipping alert with unparseable start_time: %r",
                alert.start_time,
            )
            continue
        if start > now:
            upcoming.append(alert)
    _max_utc = datetime.max.replace(tzinfo=UTC)
    upcoming.sort(key=lambda a: _parse_iso_to_utc(a.start_time) or _max_utc)
    return upcoming


# ---------------------------------------------------------------------------
# Location-based alert filtering
# ---------------------------------------------------------------------------


def filter_by_location(
    alerts: list[Alert],
    location_filters: list[str] | str | None = None,
) -> list[Alert]:
    """Filter alerts by location.

    Perform case-insensitive partial matching. An alert is included
    if any of its locations contains any of the filter strings.

    If *location_filters* is empty or ``None``, all alerts are returned.
    Accepts a single comma-separated string or a list of strings.

    Args:
        alerts: List of alerts to filter.
        location_filters: Location strings (or single comma-separated string).

    Returns:
        Filtered list of alerts.

    """
    if not location_filters:
        return alerts

    # Normalise: accept a single comma-separated string from TextSelector
    if isinstance(location_filters, str):
        location_filters = [f.strip() for f in location_filters.split(",") if f.strip()]

    if not location_filters:
        return alerts

    filters_lower = [f.lower() for f in location_filters]

    filtered: list[Alert] = []
    for alert in alerts:
        for location in alert.locations:
            location_lower = location.lower()
            if any(filter_str in location_lower for filter_str in filters_lower):
                filtered.append(alert)
                break

    if len(filtered) < len(alerts):
        _LOGGER.debug(
            "Location filtering: %d alerts matched, %d filtered out",
            len(filtered),
            len(alerts) - len(filtered),
        )

    return filtered
