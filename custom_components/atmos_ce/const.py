"""Constants for the Atmos CE integration."""
from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final

# Integration domain
DOMAIN: Final = "atmos_ce"

# Version (kept in sync with manifest.json, update both together)
VERSION: Final = "1.0.1"

# Default User-Agent for outbound HTTP requests. Several upstream APIs
# (NWS, Meteoalarm, Met Office) ask for an identifying UA with contact.
DEFAULT_USER_AGENT: Final = (
    f"atmos_ce/{VERSION} (+https://github.com/hiall-fyi/atmos_ce)"
)

# Canonical set of alert types: every _classify_event() must return one of these.
ALERT_TYPES: Final = frozenset({
    "rain",
    "wind",
    "snow",
    "ice",
    "fog",
    "thunderstorm",
    "heat",
    "cold",
    "flood",
    "tornado",
    "fire",
    "coastal",
    "avalanche",
    "unknown",
})

# Icon mapping: must have an entry for every member of ALERT_TYPES.
ICON_MAP: Final = {
    "rain": "mdi:weather-pouring",
    "wind": "mdi:weather-windy",
    "snow": "mdi:weather-snowy",
    "ice": "mdi:snowflake",
    "fog": "mdi:weather-fog",
    "thunderstorm": "mdi:weather-lightning",
    "heat": "mdi:weather-sunny-alert",
    "cold": "mdi:snowflake-alert",
    "flood": "mdi:home-flood",
    "tornado": "mdi:weather-tornado",
    "fire": "mdi:fire-alert",
    "coastal": "mdi:waves",
    "avalanche": "mdi:image-filter-hdr",
    "unknown": "mdi:alert",
}

# Color mapping (hex colors for UI). Aligned to the canonical CAP severity
# scale in source_base.py SEVERITY_MAP — levels 1+2 are yellow (CAP minor /
# European advisory), 3 is amber/orange (severe), 4 is red (extreme). Keep
# these two tables in lockstep: a mismatch colours alerts at the wrong tier.
COLOR_MAP: Final = {
    1: "#FFFF00",  # Minor / yellow
    2: "#FFFF00",  # Moderate / yellow (European advisory)
    3: "#FFA500",  # Severe / amber / orange
    4: "#FF0000",  # Extreme / red
}

# HTTP request retry settings.
# With MAX_RETRY_ATTEMPTS=3 we make up to three HTTP attempts, sleeping
# between them using decorrelated jitter on top of the base:
#   attempt 1 -> (fail) -> sleep uniform(base, base**1) = up to 2s
#   attempt 2 -> (fail) -> sleep uniform(base, base**2) = up to 4s
#   attempt 3 -> (fail) -> raise
# Upper bound is clamped by MAX_RETRY_DELAY.
MAX_RETRY_ATTEMPTS: Final = 3
RETRY_BASE_DELAY: Final = 2  # seconds; exponential backoff base
MAX_RETRY_DELAY: Final = 30  # seconds, cap to prevent runaway delays

# HTTP request timeout (seconds), used by config flow validation
HTTP_TIMEOUT: Final = 30

# ---------------------------------------------------------------------------
# Atmospheric stability assessment
# ---------------------------------------------------------------------------


class StabilityTier(IntEnum):
    """NWS SPC-style categorical severity tiers.

    Integer values enable direct comparison: higher = more severe.
    """

    NONE = 0
    MARGINAL = 1
    SLIGHT = 2
    ENHANCED = 3
    MODERATE = 4
    HIGH = 5


# String labels for sensor state (lowercase, matching NWS SPC naming)
STABILITY_TIER_LABELS: Final[dict[StabilityTier, str]] = {
    StabilityTier.NONE: "none",
    StabilityTier.MARGINAL: "marginal",
    StabilityTier.SLIGHT: "slight",
    StabilityTier.ENHANCED: "enhanced",
    StabilityTier.MODERATE: "moderate",
    StabilityTier.HIGH: "high",
}

# Options list for SensorDeviceClass.ENUM (includes "unknown" for missing data)
STABILITY_TIER_OPTIONS: Final[list[str]] = [
    "none", "marginal", "slight", "enhanced", "moderate", "high", "unknown",
]

# Dynamic icons for composite assessment sensor (per-tier)
STABILITY_TIER_ICONS: Final[dict[StabilityTier, str]] = {
    StabilityTier.NONE: "mdi:weather-sunny",
    StabilityTier.MARGINAL: "mdi:weather-partly-cloudy",
    StabilityTier.SLIGHT: "mdi:weather-cloudy-alert",
    StabilityTier.ENHANCED: "mdi:weather-lightning",
    StabilityTier.MODERATE: "mdi:weather-lightning-rainy",
    StabilityTier.HIGH: "mdi:alert-octagon",
}

# ---------------------------------------------------------------------------
# Derived weather insight classifications
# ---------------------------------------------------------------------------


class DewPointComfort(StrEnum):
    """Dew point comfort classification."""

    DRY = "dry"
    COMFORTABLE = "comfortable"
    SLIGHTLY_HUMID = "slightly_humid"
    HUMID = "humid"
    OPPRESSIVE = "oppressive"


class VisibilityCategory(StrEnum):
    """Visibility condition classification."""

    CLEAR = "clear"
    GOOD = "good"
    MODERATE = "moderate"
    POOR = "poor"
    FOG = "fog"


class FeelsLikeContext(StrEnum):
    """Feels-like temperature context."""

    WIND_CHILL = "wind_chill"
    HEAT_INDEX = "heat_index"
    NEUTRAL = "neutral"


class PressureTrend(StrEnum):
    """Three-hour pressure trend."""

    RISING = "rising"
    STEADY = "steady"
    FALLING = "falling"


# Options lists for SensorDeviceClass.ENUM
DEW_POINT_COMFORT_OPTIONS: Final[list[str]] = [e.value for e in DewPointComfort]
VISIBILITY_CATEGORY_OPTIONS: Final[list[str]] = [e.value for e in VisibilityCategory]
FEELS_LIKE_CONTEXT_OPTIONS: Final[list[str]] = [e.value for e in FeelsLikeContext]
PRESSURE_TREND_OPTIONS: Final[list[str]] = [e.value for e in PressureTrend]

# Trend symbols for pressure trend extra attributes
PRESSURE_TREND_SYMBOLS: Final[dict[PressureTrend, str]] = {
    PressureTrend.RISING: "↑",
    PressureTrend.STEADY: "→",
    PressureTrend.FALLING: "↓",
}

# Pressure trend threshold (hPa over 3 hours)
PRESSURE_TREND_THRESHOLD: Final[float] = 1.0

# Pressure history retention (hours)
PRESSURE_HISTORY_RETENTION_H: Final[int] = 4
PRESSURE_TREND_WINDOW_H: Final[int] = 3
