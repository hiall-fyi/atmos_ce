"""Pure-math astronomical calculations for sun and moon data.

All calculations use only stdlib ``math``, ``datetime``, and ``calendar``.
No external dependencies. Algorithms based on NOAA Solar Calculator
and Jean Meeus "Astronomical Algorithms".
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEG2RAD: Final = math.pi / 180.0
_RAD2DEG: Final = 180.0 / math.pi
_SYNODIC_MONTH: Final = 29.53058868  # days, mean synodic month

# Moon rise/set altitude correction constants (Meeus "Astronomical
# Algorithms" 2nd ed., ch. 15 eq. 15.1). The geometric altitude at
# moonrise/moonset is h0 = 0.7275 * pi - 34', where pi is the horizontal
# parallax (mean 0.9507 deg) and 34' (0.5667 deg) accounts for mean
# atmospheric refraction.
_MOON_PARALLAX_DEG: Final = 0.9507
_MOON_REFRACTION_DEG: Final = 0.5667

# Moon phase machine identifiers in order (8 phases, each ~3.69 days).
# These are the stable state values surfaced by the moon_phase ENUM
# sensor; the user-facing display names live in strings.json /
# translations/*.json under `sensor.moon_phase.state.<id>`.
MOON_PHASES: Final = (
    "new_moon",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full_moon",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
)

# Sun elevation angles for golden/blue hour boundaries
_GOLDEN_HOUR_LOW: Final = -4.0   # degrees
_GOLDEN_HOUR_HIGH: Final = 6.0   # degrees
_BLUE_HOUR_LOW: Final = -6.0     # degrees
_BLUE_HOUR_HIGH: Final = -4.0    # degrees


# ---------------------------------------------------------------------------
# NOAA Solar Calculator helpers
# ---------------------------------------------------------------------------


def _julian_day(dt: date) -> float:
    """Convert a date to Julian Day number."""
    y = dt.year
    m = dt.month
    d = dt.day
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def _julian_century(jd: float) -> float:
    """Convert Julian Day to Julian Century."""
    return (jd - 2451545.0) / 36525.0


def _sun_geometric_mean_longitude(t: float) -> float:
    """Sun geometric mean longitude (degrees)."""
    return (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0


def _sun_geometric_mean_anomaly(t: float) -> float:
    """Sun geometric mean anomaly (degrees)."""
    return 357.52911 + t * (35999.05029 - 0.0001537 * t)


def _earth_orbit_eccentricity(t: float) -> float:
    """Eccentricity of Earth's orbit."""
    return 0.016708634 - t * (0.000042037 + 0.0000001267 * t)


def _sun_equation_of_center(t: float) -> float:
    """Sun equation of center (degrees)."""
    m = _sun_geometric_mean_anomaly(t) * _DEG2RAD
    return (
        math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * m) * (0.019993 - 0.000101 * t)
        + math.sin(3 * m) * 0.000289
    )


def _sun_true_longitude(t: float) -> float:
    """Sun true longitude (degrees)."""
    return _sun_geometric_mean_longitude(t) + _sun_equation_of_center(t)


def _sun_apparent_longitude(t: float) -> float:
    """Sun apparent longitude (degrees)."""
    omega = 125.04 - 1934.136 * t
    return _sun_true_longitude(t) - 0.00569 - 0.00478 * math.sin(omega * _DEG2RAD)


def _mean_obliquity_ecliptic(t: float) -> float:
    """Mean obliquity of the ecliptic (degrees)."""
    return 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0


def _obliquity_correction(t: float) -> float:
    """Corrected obliquity of the ecliptic (degrees)."""
    omega = 125.04 - 1934.136 * t
    return _mean_obliquity_ecliptic(t) + 0.00256 * math.cos(omega * _DEG2RAD)


def _sun_declination(t: float) -> float:
    """Sun declination (degrees)."""
    e = _obliquity_correction(t) * _DEG2RAD
    lam = _sun_apparent_longitude(t) * _DEG2RAD
    return math.asin(math.sin(e) * math.sin(lam)) * _RAD2DEG


def _equation_of_time(t: float) -> float:
    """Equation of time (minutes)."""
    e = _earth_orbit_eccentricity(t)
    eps = _obliquity_correction(t) * _DEG2RAD
    l0 = _sun_geometric_mean_longitude(t) * _DEG2RAD
    m = _sun_geometric_mean_anomaly(t) * _DEG2RAD

    y = math.tan(eps / 2.0) ** 2

    eot = (
        y * math.sin(2 * l0)
        - 2 * e * math.sin(m)
        + 4 * e * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * e * e * math.sin(2 * m)
    )
    return 4.0 * eot * _RAD2DEG


def _hour_angle_for_elevation(
    latitude: float, declination: float, elevation: float,
) -> tuple[float | None, bool, bool]:
    """Calculate hour angle for a given sun elevation.

    Returns a tuple ``(hour_angle_deg, always_up, always_down)`` so callers
    can distinguish polar day (sun above the elevation all day) from polar
    night (sun below all day), which a single ``None`` sentinel can't.

    Args:
        latitude: Observer latitude (degrees).
        declination: Sun declination (degrees).
        elevation: Target sun elevation angle (degrees).
            Standard sunrise/sunset uses -0.8333 (accounting for refraction).

    Returns:
        ``(hour_angle_deg, False, False)`` in the normal case, or
        ``(None, True, False)`` when the sun is always above the threshold
        (polar day), or ``(None, False, True)`` when it is always below
        (polar night).

    """
    lat_rad = latitude * _DEG2RAD
    dec_rad = declination * _DEG2RAD
    el_rad = elevation * _DEG2RAD

    cos_ha = (
        math.sin(el_rad) - math.sin(lat_rad) * math.sin(dec_rad)
    ) / (math.cos(lat_rad) * math.cos(dec_rad))

    if cos_ha < -1.0:
        return None, True, False   # always above elevation, polar day
    if cos_ha > 1.0:
        return None, False, True   # always below elevation, polar night
    return math.acos(cos_ha) * _RAD2DEG, False, False


def _solar_noon_minutes(longitude: float, eqtime: float, tz_offset: float) -> float:
    """Calculate solar noon in minutes from midnight (local time)."""
    return 720.0 - 4.0 * longitude - eqtime + tz_offset * 60.0


def _time_from_minutes(dt: date, minutes: float, tz_offset: float) -> datetime | None:
    """Convert minutes-from-local-midnight to a timezone-aware datetime.

    A minute outside ``[0, 1440)`` belongs to an adjacent calendar day
    (when ``tz_offset`` and ``longitude`` disagree, e.g. a forecast
    location far from the HA timezone). The rollover is carried into the
    date rather than wrapped onto the same day, which keeps each event at
    its true instant and preserves ``sunrise < ... < sunset`` ordering.
    """
    day_offset, minute_in_day = divmod(minutes, 1440.0)
    h = int(minute_in_day // 60)
    m = int(minute_in_day % 60)
    s = int((minute_in_day % 1) * 60)
    tz = timezone(timedelta(hours=tz_offset))
    base = datetime(dt.year, dt.month, dt.day, h, m, s, tzinfo=tz)
    return base + timedelta(days=int(day_offset))


# ---------------------------------------------------------------------------
# Public API: Sun
# ---------------------------------------------------------------------------


def sun_times(
    dt: date,
    latitude: float,
    longitude: float,
    tz_offset: float = 0.0,
) -> dict[str, object]:
    """Calculate sun event times for a given date and location.

    Args:
        dt: The date to calculate for.
        latitude: Observer latitude (-90 to 90).
        longitude: Observer longitude (-180 to 180).
        tz_offset: Timezone offset in hours from UTC (e.g. 1.0 for CET).

    Returns:
        Dict with the sunrise/sunset/golden-hour/blue-hour timestamps plus
        two booleans, ``sun_always_up`` and ``sun_always_down``, that
        disambiguate polar day from polar night. Exactly one of the two
        flags is True at a polar location; both are False elsewhere.

    """
    jd = _julian_day(dt)
    t = _julian_century(jd)
    eqtime = _equation_of_time(t)
    decl = _sun_declination(t)
    noon_min = _solar_noon_minutes(longitude, eqtime, tz_offset)

    def _event(
        elevation: float,
    ) -> tuple[datetime | None, datetime | None, bool, bool]:
        ha, always_up, always_down = _hour_angle_for_elevation(
            latitude, decl, elevation,
        )
        if ha is None:
            return None, None, always_up, always_down
        rise_min = noon_min - 4.0 * ha
        set_min = noon_min + 4.0 * ha
        return (
            _time_from_minutes(dt, rise_min, tz_offset),
            _time_from_minutes(dt, set_min, tz_offset),
            always_up,
            always_down,
        )

    sunrise, sunset, sun_always_up, sun_always_down = _event(-0.8333)
    gh_morning_start, gh_evening_end, *_ = _event(_GOLDEN_HOUR_LOW)
    gh_morning_end, gh_evening_start, *_ = _event(_GOLDEN_HOUR_HIGH)
    bh_morning_start, bh_evening_end, *_ = _event(_BLUE_HOUR_LOW)
    bh_morning_end, bh_evening_start, *_ = _event(_BLUE_HOUR_HIGH)

    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "sun_always_up": sun_always_up,
        "sun_always_down": sun_always_down,
        "golden_hour_morning_start": gh_morning_start,
        "golden_hour_morning_end": gh_morning_end,
        "golden_hour_evening_start": gh_evening_start,
        "golden_hour_evening_end": gh_evening_end,
        "blue_hour_morning_start": bh_morning_start,
        "blue_hour_morning_end": bh_morning_end,
        "blue_hour_evening_start": bh_evening_start,
        "blue_hour_evening_end": bh_evening_end,
    }


def daylight_duration(sunrise: datetime | None, sunset: datetime | None) -> float:
    """Return daylight duration in hours from a sunrise/sunset pair.

    Use ``compute_daylight_duration`` instead when polar day/night
    distinction is needed, this helper can't tell them apart.

    Args:
        sunrise: Sunrise datetime (or None).
        sunset: Sunset datetime (or None).

    Returns:
        Duration in hours, or 0.0 if either time is None.

    """
    if sunrise is None or sunset is None:
        return 0.0
    delta = (sunset - sunrise).total_seconds()
    return max(0.0, delta / 3600.0)


def compute_daylight_duration(astro_data: dict[str, object]) -> float:
    """Return daylight duration in hours, honouring polar flags.

    Unlike ``daylight_duration`` which only sees the sunrise/sunset pair,
    this helper consults ``sun_always_up`` / ``sun_always_down`` from a
    ``sun_times`` result so polar day correctly reports 24.0h and polar
    night 0.0h.

    Args:
        astro_data: A dict returned by ``sun_times`` (or a merged astro
            result containing its keys).

    Returns:
        Daylight duration in hours.

    """
    if astro_data.get("sun_always_up"):
        return 24.0
    if astro_data.get("sun_always_down"):
        return 0.0
    sunrise = astro_data.get("sunrise")
    sunset = astro_data.get("sunset")
    if not isinstance(sunrise, datetime) or not isinstance(sunset, datetime):
        return 0.0
    return daylight_duration(sunrise, sunset)


# ---------------------------------------------------------------------------
# Public API: Moon
# ---------------------------------------------------------------------------


def moon_phase(dt: date) -> dict[str, object]:
    """Calculate moon phase for a given date.

    Uses a simplified algorithm based on the known new moon reference
    date of 2000-01-06 and the mean synodic month of 29.53 days.

    Args:
        dt: The date to calculate for.

    Returns:
        Dict with keys: phase_name (str), illumination (float 0-100),
        moon_age (float 0-29.53).

    """
    # Reference new moon: 2000-01-06 18:14 UTC
    ref = datetime(2000, 1, 6, 18, 14, 0, tzinfo=UTC)
    now = datetime(dt.year, dt.month, dt.day, 12, 0, 0, tzinfo=UTC)
    days_since = (now - ref).total_seconds() / 86400.0
    moon_age = days_since % _SYNODIC_MONTH

    # Phase index (0-7)
    phase_idx = int(moon_age / (_SYNODIC_MONTH / 8.0)) % 8
    phase_name = MOON_PHASES[phase_idx]

    # Illumination: 0% at new moon, 100% at full moon
    # Uses cosine approximation
    illumination = (1.0 - math.cos(2.0 * math.pi * moon_age / _SYNODIC_MONTH)) / 2.0 * 100.0

    return {
        "phase_name": phase_name,
        "illumination": round(illumination, 1),
        "moon_age": round(moon_age, 2),
    }


def moon_times(
    dt: date,
    latitude: float,
    longitude: float,
    tz_offset: float = 0.0,
) -> dict[str, object]:
    """Calculate moonrise and moonset for a given date and location.

    Uses a simplified iterative algorithm based on Meeus. Accuracy is
    approximately ±5 minutes, sufficient for HA sensor use.

    ``moonrise`` and ``moonset`` are independent same-day events: each is
    wrapped into the local day on its own, so moonset can read earlier
    than moonrise. Treat them as standalone timestamps, don't subtract
    one from the other.

    Args:
        dt: The date to calculate for.
        latitude: Observer latitude (-90 to 90).
        longitude: Observer longitude (-180 to 180).
        tz_offset: Timezone offset in hours from UTC.

    Returns:
        Dict with ``moonrise`` / ``moonset`` (``datetime`` or ``None``) and
        ``moon_always_up`` / ``moon_always_down`` (``bool``). The wider
        ``object`` value type reflects the mixed shape; callers that only
        want the datetime entries should read those keys directly.

    """
    # Simplified moon position, use average daily motion
    # Moon moves ~13.2 degrees/day in ecliptic longitude
    # This is a low-precision method suitable for rise/set times

    jd = _julian_day(dt)
    t = _julian_century(jd)

    # Moon's mean longitude (degrees)
    moon_lon = (218.3165 + 481267.8813 * t) % 360.0
    # Moon's mean anomaly (degrees)
    moon_anom = (134.9634 + 477198.8676 * t) % 360.0
    # Moon's argument of latitude
    moon_f = (93.2720 + 483202.0175 * t) % 360.0

    # Simplified ecliptic longitude
    ecl_lon = moon_lon + 6.289 * math.sin(moon_anom * _DEG2RAD)
    # Simplified ecliptic latitude
    ecl_lat = 5.128 * math.sin(moon_f * _DEG2RAD)
    # Obliquity
    eps = _obliquity_correction(t)

    # Convert ecliptic to equatorial
    ecl_lon_rad = ecl_lon * _DEG2RAD
    ecl_lat_rad = ecl_lat * _DEG2RAD
    eps_rad = eps * _DEG2RAD

    # Right ascension and declination
    sin_ra = (
        math.sin(ecl_lon_rad) * math.cos(eps_rad)
        - math.tan(ecl_lat_rad) * math.sin(eps_rad)
    )
    cos_ra = math.cos(ecl_lon_rad)
    ra = math.atan2(sin_ra, cos_ra) * _RAD2DEG  # degrees

    decl = math.asin(
        math.sin(ecl_lat_rad) * math.cos(eps_rad)
        + math.cos(ecl_lat_rad) * math.sin(eps_rad) * math.sin(ecl_lon_rad)
    ) * _RAD2DEG

    # Moonrise/moonset altitude threshold per Meeus ch. 15 eq. 15.1:
    # h0 = 0.7275 * pi - refraction, where pi is horizontal parallax.
    moon_elevation = 0.7275 * _MOON_PARALLAX_DEG - _MOON_REFRACTION_DEG

    # Hour angle
    lat_rad = latitude * _DEG2RAD
    dec_rad = decl * _DEG2RAD
    el_rad = moon_elevation * _DEG2RAD

    cos_ha = (
        math.sin(el_rad) - math.sin(lat_rad) * math.sin(dec_rad)
    ) / (math.cos(lat_rad) * math.cos(dec_rad))

    if cos_ha < -1.0:
        # Moon always above the rise/set altitude, polar "moon-up".
        return {
            "moonrise": None,
            "moonset": None,
            "moon_always_up": True,
            "moon_always_down": False,
        }
    if cos_ha > 1.0:
        # Moon never clears the horizon, polar "moon-down".
        return {
            "moonrise": None,
            "moonset": None,
            "moon_always_up": False,
            "moon_always_down": True,
        }

    ha = math.acos(cos_ha) * _RAD2DEG

    # Local sidereal time at midnight
    gmst0 = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0
    lst = (gmst0 + longitude) % 360.0

    # Transit time (hours)
    transit = ((ra - lst + 360.0) % 360.0) / 15.0 + tz_offset

    # Rise and set times (hours from midnight)
    rise_hours = transit - ha / 15.0
    set_hours = transit + ha / 15.0

    # Normalize to 0-24
    rise_hours = rise_hours % 24.0
    set_hours = set_hours % 24.0

    tz = timezone(timedelta(hours=tz_offset))

    def _hours_to_dt(hours: float) -> datetime:
        # Clamp minute/second to 0..59, float arithmetic can produce 60
        # at representation boundaries (e.g. hours=23.99999), which
        # datetime() rejects with "minute must be in 0..59".
        h = int(hours) % 24
        m = min(59, int((hours - int(hours)) * 60))
        s = min(59, int(((hours - int(hours)) * 60 - m) * 60))
        return datetime(dt.year, dt.month, dt.day, h, m, s, tzinfo=tz)

    return {
        "moonrise": _hours_to_dt(rise_hours),
        "moonset": _hours_to_dt(set_hours),
        "moon_always_up": False,
        "moon_always_down": False,
    }
