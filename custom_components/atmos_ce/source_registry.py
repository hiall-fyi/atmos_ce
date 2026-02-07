"""Source registry for Atmos CE.

Centralises source class registration and lookup so that neither
``__init__.py`` nor ``config_flow.py`` need to import each other.
All source modules are imported eagerly at module level to avoid
synchronous ``importlib`` calls inside async contexts.
"""
from __future__ import annotations

from .source_base import WeatherWarningSource
from .sources.cwa_taiwan import CWATaiwanSource
from .sources.dwd import DWDSource
from .sources.environment_canada import EnvironmentCanadaSource
from .sources.met_office import MetOfficeSource
from .sources.meteoalarm import MeteoalarmSource
from .sources.nws import NWSSource
from .sources.worldwide_forecast import WorldwideForecastSource

_SOURCE_CLASSES: dict[str, type[WeatherWarningSource]] = {
    "dwd": DWDSource,
    "environment_canada": EnvironmentCanadaSource,
    "cwa_taiwan": CWATaiwanSource,
    "met_office": MetOfficeSource,
    "meteoalarm": MeteoalarmSource,
    "nws": NWSSource,
    "worldwide_forecast": WorldwideForecastSource,
}

# Cached singleton instances: sources are stateless so one instance suffices.
_SOURCE_INSTANCES: dict[str, WeatherWarningSource] = {}


def _get_or_create(source_id: str) -> WeatherWarningSource | None:
    """Return a cached source instance, creating it on first access.

    Args:
        source_id: Source identifier (e.g. ``"met_office"``).

    Returns:
        Source instance or None if *source_id* is unknown.

    """
    if source_id in _SOURCE_INSTANCES:
        return _SOURCE_INSTANCES[source_id]
    cls = _SOURCE_CLASSES.get(source_id)
    if cls is None:
        return None
    instance = cls()
    _SOURCE_INSTANCES[source_id] = instance
    return instance


def get_available_sources() -> list[WeatherWarningSource]:
    """Return a list of all available source instances (cached).

    Returns:
        List of source objects.

    """
    return [_get_or_create(sid) for sid in _SOURCE_CLASSES if _get_or_create(sid) is not None]


def get_source_by_id(source_id: str) -> WeatherWarningSource | None:
    """Return a source instance by its ID, or None if not found.

    Args:
        source_id: Source identifier (e.g. ``"met_office"``).

    Returns:
        Source instance or None.

    """
    return _get_or_create(source_id)
