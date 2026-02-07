"""Data models for Atmos CE."""
from __future__ import annotations

from dataclasses import dataclass

from .const import COLOR_MAP, ICON_MAP


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
    severity: str           # yellow, amber, red, extreme (or source-specific)
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
