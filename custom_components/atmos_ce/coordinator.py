"""Unified coordinator for Atmos CE.

Failure-handling policy: see ``~/.claude/references/ha-coordinator-pattern.md``.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .forecast_backend import OpenMeteoBackend
from .forecast_types import AirQualityData, ForecastPayload
from .helpers import get_active_alerts, get_upcoming_alerts
from .models import Alert
from .source_base import WeatherWarningSource
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertData:
    """Immutable snapshot of alert data."""

    all_alerts: list[Alert] = field(default_factory=list)
    active_alerts: list[Alert] = field(default_factory=list)
    upcoming_alerts: list[Alert] = field(default_factory=list)


@dataclass(frozen=True)
class UnifiedData:
    """Immutable snapshot of one update cycle. None = disabled or fetch failed."""

    alerts: AlertData = field(default_factory=AlertData)
    forecast: ForecastPayload | None = None
    air_quality: AirQualityData | None = None
    astro: dict[str, object] = field(default_factory=dict)


# Errors `_dispatch_fetches` captures so a single-backend failure can still
# leave the other backend's data fresh. Auth failures and programmer bugs
# are deliberately absent so they propagate to HA's standard handling.
_RECOVERABLE_ERRORS = (
    aiohttp.ClientConnectionError,
    aiohttp.ClientResponseError,
    TimeoutError,
    ValueError,
    KeyError,
)


class UnifiedCoordinator(DataUpdateCoordinator[UnifiedData]):
    """Coordinate fetching warnings + forecast + AQ + astro for one source."""

    def __init__(
        self,
        hass: HomeAssistant,
        source: WeatherWarningSource,
        forecast_backend: OpenMeteoBackend,
        config: dict[str, Any],
        storage_manager: StorageManager,
        update_interval: timedelta,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the UnifiedCoordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Atmos CE - {source.source_name}",
            update_interval=update_interval,
            config_entry=config_entry,
        )
        self.source = source
        self.forecast_backend = forecast_backend
        self.config = self._resolve_config(config, hass)
        self.storage_manager = storage_manager
        self.session = async_get_clientsession(hass)

    @staticmethod
    def _resolve_config(
        config: dict[str, Any],
        hass: HomeAssistant,
    ) -> dict[str, Any]:
        """Inject HA home coordinates as forecast-location fallback."""
        resolved = dict(config)
        resolved.setdefault("forecast_latitude", hass.config.latitude)
        resolved.setdefault("forecast_longitude", hass.config.longitude)
        _LOGGER.debug(
            "Resolved config: source=%s, forecast_location=(%s, %s)",
            resolved.get("source_id", "unknown"),
            resolved.get("forecast_latitude"),
            resolved.get("forecast_longitude"),
        )
        return resolved

    async def _async_update_data(self) -> UnifiedData:
        """Fetch all enabled data types in a single update cycle.

        Raises:
            UpdateFailed: If every enabled backend failed this cycle.
            ConfigEntryAuthFailed: If the source's API key is rejected.

        """
        fetch_warnings = (
            self.config.get("enable_warnings", True)
            and self.source.has_warning_backend
        )
        fetch_forecast = self.config.get("enable_forecast", True)
        fetch_aq = self.config.get("enable_air_quality", True)
        attempt_forecast = fetch_forecast or fetch_aq

        if not fetch_warnings and not attempt_forecast:
            return UnifiedData()

        try:
            warn_result, fc_result = await self._dispatch_fetches(
                fetch_warnings, fetch_forecast, fetch_aq,
            )
        except Exception:
            # A single-fetch-type cycle (only warnings or only forecast
            # attempted) raises non-recoverable errors straight through
            # _dispatch_fetches rather than returning them as a value, so
            # this must be caught here too, not just in the loop below.
            await self._save_failed_fetch()
            raise

        # Auth failures + programmer bugs bypass partial-fetch tolerance.
        for result in (warn_result, fc_result):
            if isinstance(result, BaseException) and not isinstance(
                result, _RECOVERABLE_ERRORS,
            ):
                await self._save_failed_fetch()
                raise result

        warn_failed = isinstance(warn_result, BaseException)
        fc_failed = isinstance(fc_result, BaseException)

        if (not fetch_warnings or warn_failed) and (
            not attempt_forecast or fc_failed
        ):
            # Record the failed cycle before raising, so diagnostics show
            # a degraded source rather than a stale success.
            await self._save_failed_fetch()
            self._raise_total_failure(
                fetch_warnings, attempt_forecast, warn_result, fc_result,
            )

        if warn_failed:
            alerts = AlertData()
        else:
            assert isinstance(warn_result, AlertData)  # noqa: S101 (refines union type for mypy)
            alerts = warn_result
        forecast_data: ForecastPayload | None
        aq_data: AirQualityData | None
        astro: dict[str, object]
        if fc_failed:
            forecast_data, aq_data, astro = None, None, {}
        else:
            assert isinstance(fc_result, tuple)  # noqa: S101 (refines union type for mypy)
            forecast_data, aq_data, astro = fc_result

        # last_fetch tracks the warnings backend (it carries alert_count),
        # so a cycle whose forecast succeeded but warnings failed records
        # success=False: that's "warnings degraded", not "no alerts".
        warnings_ok = not fetch_warnings or not warn_failed
        await self.storage_manager.save_last_fetch(
            self.source.source_id,
            utcnow(),
            success=warnings_ok,
            alert_count=len(alerts.all_alerts),
        )

        return UnifiedData(
            alerts=alerts,
            forecast=forecast_data,
            air_quality=aq_data,
            astro=astro,
        )

    async def _save_failed_fetch(self) -> None:
        """Record this cycle as failed so diagnostics don't show a stale success."""
        await self.storage_manager.save_last_fetch(
            self.source.source_id,
            utcnow(),
            success=False,
            alert_count=0,
        )

    async def _dispatch_fetches(
        self,
        fetch_warnings: bool,
        fetch_forecast: bool,
        fetch_aq: bool,
    ) -> tuple[
        AlertData | BaseException,
        tuple[ForecastPayload | None, AirQualityData | None, dict[str, object]]
        | BaseException,
    ]:
        """Run enabled fetches, capturing recoverable errors as return values."""
        attempt_forecast = fetch_forecast or fetch_aq
        if fetch_warnings and attempt_forecast:
            warn_result, fc_result = await asyncio.gather(
                self._fetch_warnings(),
                self._fetch_forecast_and_aq(fetch_forecast, fetch_aq),
                return_exceptions=True,
            )
            return warn_result, fc_result
        if fetch_warnings:
            try:
                warn_result = await self._fetch_warnings()
            except _RECOVERABLE_ERRORS as err:
                warn_result = err
            return warn_result, (None, None, {})
        try:
            fc_result = await self._fetch_forecast_and_aq(
                fetch_forecast, fetch_aq,
            )
        except _RECOVERABLE_ERRORS as err:
            fc_result = err
        return AlertData(), fc_result

    def _raise_total_failure(
        self,
        attempted_warnings: bool,
        attempted_forecast: bool,
        warn_result: AlertData | BaseException,
        fc_result: tuple[Any, Any, Any] | BaseException,
    ) -> None:
        """Build a descriptive UpdateFailed and raise it."""
        errors: list[str] = []
        if attempted_warnings and isinstance(warn_result, BaseException):
            errors.append(f"warnings: {warn_result}")
        if attempted_forecast and isinstance(fc_result, BaseException):
            errors.append(f"forecast/aq: {fc_result}")
        raise UpdateFailed(
            f"Atmos CE update failed for {self.source.source_name}: "
            f"{'; '.join(errors)}",
        )

    async def _fetch_warnings(self) -> AlertData:
        """Fetch warnings from the source's warning backend."""
        _LOGGER.debug("Fetching alerts from %s", self.source.source_name)
        raw_alerts = await self.source.fetch_alerts(self.session, self.config)
        _LOGGER.debug(
            "Successfully fetched %d alerts from %s",
            len(raw_alerts), self.source.source_name,
        )
        return AlertData(
            all_alerts=raw_alerts,
            active_alerts=get_active_alerts(raw_alerts),
            upcoming_alerts=get_upcoming_alerts(raw_alerts),
        )

    async def _fetch_forecast_and_aq(
        self,
        fetch_forecast: bool,
        fetch_aq: bool,
    ) -> tuple[ForecastPayload | None, AirQualityData | None, dict[str, object]]:
        """Fetch forecast, air quality, and astro data from Open-Meteo."""
        lat = self.config.get("forecast_latitude", self.hass.config.latitude)
        lon = self.config.get("forecast_longitude", self.hass.config.longitude)

        forecast_data: ForecastPayload | None = None
        if fetch_forecast:
            _LOGGER.debug(
                "Fetching forecast from Open-Meteo (lat=%s, lon=%s)", lat, lon,
            )
            raw = await self.forecast_backend.fetch_forecast(
                self.session, lat, lon,
            )
            try:
                forecast_data = {
                    "current": self.forecast_backend.parse_current_conditions(raw),
                    "hourly": self.forecast_backend.parse_hourly_forecast(raw),
                    "daily": self.forecast_backend.parse_daily_forecast(raw),
                }
            except KeyError:
                # The parsers tolerate missing upstream fields, so a
                # KeyError here is a payload-shape bug, not a transient
                # gap. Log it before it joins the recoverable-error path.
                _LOGGER.exception(
                    "Forecast payload shape drift parsing Open-Meteo "
                    "response for %s", self.source.source_name,
                )
                raise

        aq_data = await self._fetch_air_quality(lat, lon) if fetch_aq else None
        astro = self._compute_astro(lat, lon, self.hass.config.time_zone)
        _LOGGER.debug("Successfully fetched forecast/AQ data from Open-Meteo")
        return forecast_data, aq_data, astro

    async def _fetch_air_quality(
        self, latitude: float, longitude: float,
    ) -> AirQualityData | None:
        """Fetch air-quality data; failure is non-fatal (sub-resource fallback)."""
        try:
            raw = await self.forecast_backend.fetch_air_quality(
                self.session, latitude, longitude,
            )
            return self.forecast_backend.parse_air_quality(raw)
        except _RECOVERABLE_ERRORS as aqi_err:
            _LOGGER.warning(
                "Failed to fetch air quality data (non-fatal): %s", aqi_err,
            )
            return None

    @staticmethod
    def _compute_astro(
        latitude: float,
        longitude: float,
        time_zone: str | None,
    ) -> dict[str, object]:
        """Compute today's sun / moon / daylight values for the given location.

        ``time_zone`` is used to pick the local date and rotate rise/set
        times so each day's pair falls inside [00:00, 24:00) local
        instead of crossing midnight UTC. ``None`` / unknown zone → UTC.
        """
        from .astro import compute_daylight_duration, moon_phase, moon_times, sun_times  # noqa: PLC0415

        try:
            tz: tzinfo = UTC
            if time_zone:
                try:
                    tz = ZoneInfo(time_zone)
                except ZoneInfoNotFoundError:
                    _LOGGER.debug(
                        "Unknown time zone %r, falling back to UTC", time_zone,
                    )

            now_local = datetime.now(tz=tz)
            today = now_local.date()
            utc_offset = now_local.utcoffset() or timedelta(0)
            tz_offset_h = utc_offset.total_seconds() / 3600.0

            st = sun_times(today, latitude, longitude, tz_offset=tz_offset_h)
            mp = moon_phase(today)
            mt = moon_times(today, latitude, longitude, tz_offset=tz_offset_h)
            # compute_daylight_duration distinguishes polar day (24h) from
            # polar night (0h); daylight_duration alone cannot.
            dl = compute_daylight_duration(st)

            result: dict[str, object] = {**st, **mp, **mt}
            result["daylight_duration"] = round(dl, 2)
            return result
        except Exception:
            _LOGGER.exception("Error computing astronomical data")
            return {}
