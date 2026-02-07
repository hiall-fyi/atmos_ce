"""Atmospheric stability computation module.

Pure functions for deriving stability parameters from Open-Meteo
pressure-level data. No Home Assistant dependencies: all functions
accept raw values and return computed results or None.

Derived parameters:
- Bulk wind shear (0–6 km) from 500 hPa and surface wind
- Mid-level lapse rate (700–500 hPa) from pressure-level temperatures
- Estimated LCL height from surface temperature and dew point
- Composite stability assessment combining CAPE, LI, shear, lapse rate
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from .const import STABILITY_TIER_LABELS, StabilityTier

# ---------------------------------------------------------------------------
# Total number of parameters in the composite assessment
# ---------------------------------------------------------------------------

_TOTAL_PARAMETERS: Final = 4

# ---------------------------------------------------------------------------
# Confidence labels based on parameter availability
# ---------------------------------------------------------------------------

_CONFIDENCE_MAP: Final[dict[int, str]] = {
    4: "full",
    3: "high",
    2: "partial",
    1: "low",
}


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StabilityAssessment:
    """Result of composite stability assessment."""

    tier: StabilityTier
    tier_label: str
    cape_tier: StabilityTier | None
    lifted_index_tier: StabilityTier | None
    wind_shear_tier: StabilityTier | None
    lapse_rate_tier: StabilityTier | None
    cape_value: float | None
    lifted_index_value: float | None
    wind_shear_value: float | None
    lapse_rate_value: float | None
    parameters_available: int
    parameters_total: int
    confidence: str


# ---------------------------------------------------------------------------
# Derived parameter computations
# ---------------------------------------------------------------------------


def compute_wind_shear(
    sfc_speed: float | None,
    sfc_direction: float | None,
    upper_speed: float | None,
    upper_direction: float | None,
) -> float | None:
    """Compute 0–6 km bulk wind shear magnitude (km/h).

    Uses vector difference between 500 hPa wind (~5.6 km) and
    10 m surface wind.  Surface wind comes from the coordinator's
    ``current["wind_speed"]`` (= Open-Meteo ``wind_speed_10m``) and
    ``current["wind_direction"]`` (= Open-Meteo ``wind_direction_10m``).

    Args:
        sfc_speed: Surface wind speed in km/h.
        sfc_direction: Surface wind direction in degrees (meteorological).
        upper_speed: 500 hPa wind speed in km/h.
        upper_direction: 500 hPa wind direction in degrees (meteorological).

    Returns:
        Shear magnitude in km/h rounded to 1 decimal place,
        or ``None`` if any input is missing.

    """
    if (
        sfc_speed is None or sfc_direction is None
        or upper_speed is None or upper_direction is None
    ):
        return None

    # Meteorological convention: direction is where wind comes FROM.
    # u = -speed * sin(dir), v = -speed * cos(dir)
    sfc_rad = math.radians(sfc_direction)
    upper_rad = math.radians(upper_direction)

    u_sfc = -sfc_speed * math.sin(sfc_rad)
    v_sfc = -sfc_speed * math.cos(sfc_rad)
    u_upper = -upper_speed * math.sin(upper_rad)
    v_upper = -upper_speed * math.cos(upper_rad)

    du = u_upper - u_sfc
    dv = v_upper - v_sfc

    return round(math.sqrt(du * du + dv * dv), 1)


def compute_lapse_rate(
    temp_700: float | None,
    temp_500: float | None,
    height_700: float | None,
    height_500: float | None,
) -> float | None:
    """Compute 700–500 hPa environmental lapse rate (°C/km).

    A positive value means temperature decreases with altitude (normal).
    Values > 9.8 °C/km exceed the dry adiabatic lapse rate.

    Args:
        temp_700: Temperature at 700 hPa in °C.
        temp_500: Temperature at 500 hPa in °C.
        height_700: Geopotential height at 700 hPa in meters.
        height_500: Geopotential height at 500 hPa in meters.

    Returns:
        Lapse rate in °C/km rounded to 1 decimal place,
        or ``None`` if any input is missing or height difference ≤ 0.

    """
    if (
        temp_700 is None or temp_500 is None
        or height_700 is None or height_500 is None
    ):
        return None

    dz = height_500 - height_700
    if dz <= 0:
        return None

    return round((temp_700 - temp_500) / dz * 1000, 1)


def compute_lcl_height(
    temperature: float | None,
    dew_point: float | None,
) -> int | None:
    """Estimate Lifting Condensation Level height (meters AGL).

    Uses the Espy/Magnus approximation: ``LCL ≈ 125 × (T - Td)``.
    Accuracy is approximately ±200 m.

    Inputs come from existing current conditions:
    ``current["temperature"]`` (= Open-Meteo ``temperature_2m``) and
    ``current["dew_point"]`` (= Open-Meteo ``dew_point_2m``).

    Args:
        temperature: Surface temperature in °C.
        dew_point: Surface dew point in °C.

    Returns:
        LCL height in meters (integer, clamped ≥ 0), or ``None``.

    """
    if temperature is None or dew_point is None:
        return None

    lcl = 125.0 * (temperature - dew_point)
    return max(0, round(lcl))


# ---------------------------------------------------------------------------
# Tier classification: threshold tables and classifiers
# ---------------------------------------------------------------------------

# CAPE thresholds (J/kg): higher = more unstable
_CAPE_THRESHOLDS: Final[tuple[tuple[float, StabilityTier], ...]] = (
    (300, StabilityTier.NONE),
    (1000, StabilityTier.MARGINAL),
    (2000, StabilityTier.SLIGHT),
    (3000, StabilityTier.ENHANCED),
    (4000, StabilityTier.MODERATE),
)

# Lifted Index thresholds: more negative = more unstable
# Walked from most unstable to least unstable
_LI_THRESHOLDS: Final[tuple[tuple[float, StabilityTier], ...]] = (
    (-6, StabilityTier.HIGH),
    (-4, StabilityTier.MODERATE),
    (-2, StabilityTier.ENHANCED),
    (0, StabilityTier.SLIGHT),
    (2, StabilityTier.MARGINAL),
)

# Wind shear thresholds (km/h): higher = more organized convection
_SHEAR_THRESHOLDS: Final[tuple[tuple[float, StabilityTier], ...]] = (
    (30, StabilityTier.NONE),
    (40, StabilityTier.MARGINAL),
    (50, StabilityTier.SLIGHT),
    (60, StabilityTier.ENHANCED),
    (75, StabilityTier.MODERATE),
)

# Lapse rate thresholds (°C/km): steeper = more unstable
_LAPSE_THRESHOLDS: Final[tuple[tuple[float, StabilityTier], ...]] = (
    (6.0, StabilityTier.NONE),
    (6.5, StabilityTier.MARGINAL),
    (7.5, StabilityTier.SLIGHT),
    (8.0, StabilityTier.ENHANCED),
    (9.0, StabilityTier.MODERATE),
)


def classify_cape(value: float) -> StabilityTier:
    """Classify CAPE value (J/kg) into a stability tier.

    Args:
        value: CAPE in J/kg.

    Returns:
        Stability tier.

    """
    for threshold, tier in _CAPE_THRESHOLDS:
        if value < threshold:
            return tier
    return StabilityTier.HIGH


def classify_lifted_index(value: float) -> StabilityTier:
    """Classify Lifted Index value into a stability tier.

    LI is inverted: more negative = more unstable. Boundaries are
    severe-side-inclusive, a reading of exactly -6.0 classifies as
    HIGH, -4.0 as MODERATE, etc.

    Args:
        value: Lifted Index (dimensionless).

    Returns:
        Stability tier.

    """
    for threshold, tier in _LI_THRESHOLDS:
        if value <= threshold:
            return tier
    return StabilityTier.NONE


def classify_wind_shear(value: float) -> StabilityTier:
    """Classify 0–6 km bulk wind shear (km/h) into a stability tier.

    Args:
        value: Wind shear magnitude in km/h.

    Returns:
        Stability tier.

    """
    for threshold, tier in _SHEAR_THRESHOLDS:
        if value < threshold:
            return tier
    return StabilityTier.HIGH


def classify_lapse_rate(value: float) -> StabilityTier:
    """Classify 700–500 hPa lapse rate (°C/km) into a stability tier.

    Args:
        value: Lapse rate in °C/km.

    Returns:
        Stability tier.

    """
    for threshold, tier in _LAPSE_THRESHOLDS:
        if value < threshold:
            return tier
    return StabilityTier.HIGH


# ---------------------------------------------------------------------------
# Composite stability assessment
# ---------------------------------------------------------------------------


def compute_stability_assessment(
    cape: float | None,
    lifted_index: float | None,
    wind_shear: float | None,
    lapse_rate: float | None,
) -> StabilityAssessment:
    """Compute composite stability assessment from available parameters.

    The composite tier is the maximum (worst-case) of all available
    individual parameter tiers.  If both CAPE and Lifted Index are
    ``None``, the assessment is ``"unknown"`` because the two primary
    instability indicators are missing.

    Args:
        cape: CAPE value in J/kg, or ``None``.
        lifted_index: Lifted Index value, or ``None``.
        wind_shear: Computed wind shear in km/h, or ``None``.
        lapse_rate: Computed lapse rate in °C/km, or ``None``.

    Returns:
        Composite stability assessment.

    """
    # Classify each available parameter
    cape_tier = classify_cape(cape) if cape is not None else None
    li_tier = classify_lifted_index(lifted_index) if lifted_index is not None else None
    shear_tier = classify_wind_shear(wind_shear) if wind_shear is not None else None
    lapse_tier = classify_lapse_rate(lapse_rate) if lapse_rate is not None else None

    # Collect available tiers
    available_tiers: list[StabilityTier] = [
        t for t in (cape_tier, li_tier, shear_tier, lapse_tier) if t is not None
    ]
    parameters_available = len(available_tiers)

    # If both primary indicators are missing → unknown
    if cape is None and lifted_index is None:
        return StabilityAssessment(
            tier=StabilityTier.NONE,
            tier_label="unknown",
            cape_tier=cape_tier,
            lifted_index_tier=li_tier,
            wind_shear_tier=shear_tier,
            lapse_rate_tier=lapse_tier,
            cape_value=cape,
            lifted_index_value=lifted_index,
            wind_shear_value=wind_shear,
            lapse_rate_value=lapse_rate,
            parameters_available=parameters_available,
            parameters_total=_TOTAL_PARAMETERS,
            confidence=_CONFIDENCE_MAP.get(parameters_available, "low"),
        )

    # Composite = worst-case of available tiers
    composite = max(available_tiers) if available_tiers else StabilityTier.NONE

    return StabilityAssessment(
        tier=composite,
        tier_label=STABILITY_TIER_LABELS.get(composite, "none"),
        cape_tier=cape_tier,
        lifted_index_tier=li_tier,
        wind_shear_tier=shear_tier,
        lapse_rate_tier=lapse_tier,
        cape_value=cape,
        lifted_index_value=lifted_index,
        wind_shear_value=wind_shear,
        lapse_rate_value=lapse_rate,
        parameters_available=parameters_available,
        parameters_total=_TOTAL_PARAMETERS,
        confidence=_CONFIDENCE_MAP.get(parameters_available, "low"),
    )
