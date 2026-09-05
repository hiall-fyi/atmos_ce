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

    All entities from a single config entry share this device. Worldwide
    Forecast is user-named via its own ``location_name`` field (the only
    source with one), so its device reads e.g. "Home Forecast" instead of
    the generic "Worldwide Forecast" every entry would otherwise share.
    """
    latitude = config.get("forecast_latitude", hass_latitude)
    longitude = config.get("forecast_longitude", hass_longitude)
    location_name = config.get("location_name")
    device_name = f"{location_name} Forecast" if location_name else source_name

    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=device_name,
        manufacturer="Atmos CE",
        model=f"{source_name} Weather",
        configuration_url=f"https://www.google.com/maps?q={latitude},{longitude}",
    )


def build_device_info(
    coordinator: UnifiedCoordinator,
    entry_id: str,
) -> DeviceInfo:
    """Build DeviceInfo from a coordinator and entry ID."""
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


def _parse_iso_to_utc(value: str) -> datetime | None:
    """Parse an ISO-8601 datetime and normalise to UTC.

    Naive input is treated as UTC rather than left tz-naive, so callers can
    subtract it from ``utcnow()`` without a TypeError, and alerts from
    sources with different UTC offsets sort by real instant rather than by
    raw ISO string (which would put "10:00-02:00" before "11:00+00:00" even
    though they represent the same UTC moment).
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


def calculate_progress(start_str: str, end_str: str) -> float:
    """Calculate alert progress as percentage elapsed (0-100).

    Returns 0.0 if ``end_str`` is empty (no expiry / "until further notice").
    """
    if not end_str:
        return 0.0
    start = _parse_iso_to_utc(start_str)
    end = _parse_iso_to_utc(end_str)
    if start is None or end is None:
        _LOGGER.warning("Error calculating progress: unparseable start/end time")
        return 0.0
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (utcnow() - start).total_seconds() / total * 100))


def seconds_until(time_str: str) -> int:
    """Calculate seconds from now until *time_str*.

    Returns a large sentinel (999999) if ``time_str`` is empty, indicating
    no defined end time.
    """
    if not time_str:
        return 999_999
    parsed = _parse_iso_to_utc(time_str)
    if parsed is None:
        _LOGGER.warning("Error calculating seconds_until: unparseable time %r", time_str)
        return 0
    return int((parsed - utcnow()).total_seconds())


# ---------------------------------------------------------------------------
# Shared alert filtering
# ---------------------------------------------------------------------------


def sort_alerts_by_severity(alerts: list[Alert]) -> list[Alert]:
    """Return alerts sorted by severity (level desc) then start time (asc).

    Single source of truth for severity-first ordering, shared by
    ``get_active_alerts``, ``get_upcoming_alerts``, and the ``all_alerts``
    sensor attribute so their orderings cannot drift. Returns a new list;
    the input is not mutated. Unparseable start times sort last within a
    level.
    """
    _min_utc = datetime.min.replace(tzinfo=UTC)
    return sorted(
        alerts,
        key=lambda a: (-a.level, _parse_iso_to_utc(a.start_time) or _min_utc),
    )


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
    # Severity-first ordering via the shared helper (single source of
    # truth, see sort_alerts_by_severity).
    return sort_alerts_by_severity(active)


def get_upcoming_alerts(data: list[Alert] | None) -> list[Alert]:
    """Return future alerts sorted by severity then start time.

    Alerts with an empty ``end_time`` are included if their start time
    is in the future (they will move to active once started).

    Args:
        data: List of Alert objects (or None).

    Returns:
        Upcoming alerts sorted by severity (level desc) then start time (asc).

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
    # Severity-first ordering (shared helper) so a higher-severity alert
    # that starts later is not masked by an earlier lower-severity one.
    return sort_alerts_by_severity(upcoming)


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
