"""Derived weather insight computation module.

Pure functions for classifying raw weather data into human-readable
tiers. No Home Assistant dependencies: all functions accept raw
values and return computed results or None.

Derived insights:
- Dew point comfort tier (dry → oppressive)
- Visibility category (fog → clear)
- Feels-like context (wind chill / heat index / neutral)
- Pressure trend (rising / steady / falling)
"""
from __future__ import annotations

from typing import Final

from .const import (
    PRESSURE_TREND_THRESHOLD,
    DewPointComfort,
    FeelsLikeContext,
    PressureTrend,
    VisibilityCategory,
)

# ---------------------------------------------------------------------------
# Dew point comfort classification
# ---------------------------------------------------------------------------

_DEW_POINT_THRESHOLDS: Final[tuple[tuple[float, DewPointComfort], ...]] = (
    (10.0, DewPointComfort.DRY),
    (16.0, DewPointComfort.COMFORTABLE),
    (19.0, DewPointComfort.SLIGHTLY_HUMID),
    (22.0, DewPointComfort.HUMID),
)


def classify_dew_point_comfort(dew_point: float) -> DewPointComfort:
    """Classify dew point temperature into a comfort tier.

    Thresholds (°C): <10 dry, 10–15 comfortable, 16–18 slightly humid,
    19–21 humid, ≥22 oppressive.
    """
    for threshold, tier in _DEW_POINT_THRESHOLDS:
        if dew_point < threshold:
            return tier
    return DewPointComfort.OPPRESSIVE


# ---------------------------------------------------------------------------
# Visibility category classification
# ---------------------------------------------------------------------------

_VISIBILITY_THRESHOLDS: Final[tuple[tuple[float, VisibilityCategory], ...]] = (
    (1.0, VisibilityCategory.FOG),
    (2.0, VisibilityCategory.POOR),
    (5.0, VisibilityCategory.MODERATE),
    (10.0, VisibilityCategory.GOOD),
)


def classify_visibility(visibility_km: float) -> VisibilityCategory:
    """Classify visibility distance into a category.

    Thresholds (km): <1 fog, 1–2 poor, 2–5 moderate, 5–10 good, >10 clear.
    Walks from lowest threshold (fog) upward, matching the
    ``_classify_aqi()`` pattern in ``forecast_backend.py``.
    """
    for threshold, category in _VISIBILITY_THRESHOLDS:
        if visibility_km < threshold:
            return category
    return VisibilityCategory.CLEAR


# ---------------------------------------------------------------------------
# Feels-like context classification
# ---------------------------------------------------------------------------

_FEELS_LIKE_THRESHOLD: Final[float] = 3.0


def classify_feels_like_context(
    temperature: float,
    apparent_temperature: float,
) -> FeelsLikeContext:
    """Classify feels-like context based on temperature difference.

    Wind chill when apparent < actual by more than 3°C,
    heat index when apparent > actual by more than 3°C,
    neutral otherwise.
    """
    diff = apparent_temperature - temperature
    if diff < -_FEELS_LIKE_THRESHOLD:
        return FeelsLikeContext.WIND_CHILL
    if diff > _FEELS_LIKE_THRESHOLD:
        return FeelsLikeContext.HEAT_INDEX
    return FeelsLikeContext.NEUTRAL


# ---------------------------------------------------------------------------
# Pressure trend classification
# ---------------------------------------------------------------------------


def classify_pressure_trend(
    current_pressure: float,
    pressure_3h_ago: float | None,
) -> PressureTrend | None:
    """Classify 3-hour pressure trend.

    Returns None when insufficient history (pressure_3h_ago is None).
    """
    if pressure_3h_ago is None:
        return None
    change = current_pressure - pressure_3h_ago
    if change > PRESSURE_TREND_THRESHOLD:
        return PressureTrend.RISING
    if change < -PRESSURE_TREND_THRESHOLD:
        return PressureTrend.FALLING
    return PressureTrend.STEADY
