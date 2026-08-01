"""Data models for Atmos CE."""
from __future__ import annotations

from dataclasses import dataclass

from .const import COLOR_MAP, ICON_MAP, SEVERITY_MAP, SEVERITY_NAME_BY_LEVEL


@dataclass(frozen=True, slots=True)
class Alert:
    """Represent a weather alert from any source.

    This dataclass encapsulates all information about a weather warning,
    including temporal, geographic, and display attributes.
    """

    # Identifiers
    alert_id: str           # Unique ID (source-specific or generated)
    source: str             # Source ID (e.g., "met_office", "nws")

    # Classification
    alert_type: str         # rain, wind, snow, ice, fog, thunderstorm, heat, cold
    severity: str           # A SEVERITY_MAP key agreeing with `level`
    level: int              # Numeric level 1-4 for comparison

    # Temporal
    start_time: str         # ISO 8601 format
    end_time: str           # ISO 8601 format

    # Geographic
    locations: tuple[str, ...]    # Affected areas/regions (immutable)

    # Content
    summary: str            # Short title/headline
    description: str        # Full description/details
    link: str               # URL to official alert page

    # UI
    icon: str               # MDI icon name (e.g., "mdi:weather-pouring")
    color: str              # Hex color for UI (e.g., "#FFFF00")


def get_icon_for_alert_type(alert_type: str) -> str:
    """Get MDI icon for alert type.

    Args:
        alert_type: Alert type (rain, wind, snow, etc.)

    Returns:
        MDI icon name

    """
    return ICON_MAP.get(alert_type, ICON_MAP["unknown"])


def get_color_for_level(level: int) -> str:
    """Get hex color for severity level.

    Args:
        level: Severity level (1-4)

    Returns:
        Hex color code

    """
    return COLOR_MAP.get(level, "#808080")


def resolve_severity(upstream: str | None) -> tuple[str, int]:
    """Resolve an upstream severity word to a canonical (name, level) pair.

    Deciding both together is what keeps ``Alert.severity`` from drifting
    from ``Alert.level``. Unrecognised words resolve to the lowest tier.

    Args:
        upstream: The upstream severity string (a CAP word or a colour).

    Returns:
        ``(name, level)``, where *name* is a SEVERITY_MAP key for *level*.

    """
    if not upstream:
        return "unknown", SEVERITY_MAP["unknown"]
    lowered = upstream.lower()
    level = SEVERITY_MAP.get(lowered)
    if level is None:
        return "unknown", SEVERITY_MAP["unknown"]
    return lowered, level


def get_severity_for_level(level: int) -> str:
    """Get the canonical severity name for a severity level.

    For sources that derive a level from their own wording, so they don't
    invent a vocabulary. See ``resolve_severity`` for the other direction.

    Args:
        level: Severity level (1-4)

    Returns:
        A SEVERITY_MAP key mapping back to *level*; "unknown" if out of range.

    """
    return SEVERITY_NAME_BY_LEVEL.get(level, "unknown")
