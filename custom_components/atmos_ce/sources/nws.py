"""National Weather Service weather warning source (USA).

This module implements the NWS weather warning source plugin,
which fetches alerts from the NWS API.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

import aiohttp
import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util.dt import utcnow

from ..models import (
    Alert,
    get_color_for_level,
    get_icon_for_alert_type,
    resolve_severity,
)
from ..source_base import (
    DEFAULT_FETCH_TIMEOUT,
    WeatherWarningSource,
    _as_list,
    classify_by_keywords,
    common_config_schema,
    compute_alert_id,
)

_LOGGER = logging.getLogger(__name__)


class NWSSource(WeatherWarningSource):
    """National Weather Service weather warnings (USA).

    This source fetches weather warnings from the NWS API.
    It supports Minor, Moderate, Severe, and Extreme severity levels
    for various weather types.

    Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6
    """

    API_URL = "https://api.weather.gov/alerts/active"
    _HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": "AtmosCE/2.0 (Home Assistant Integration)",
    }

    # US States (for filtering)
    US_STATES: ClassVar[list[str]] = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "AS", "GU", "MP", "PR", "VI",  # Territories
    ]

    @property
    def source_id(self) -> str:
        """Return the unique identifier for this source."""
        return "nws"

    @property
    def source_name(self) -> str:
        """Return the human-readable name for this source."""
        return "National Weather Service"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from NWS API.

        Args:
            session: aiohttp client session
            config: Source configuration

        Returns:
            List of Alert objects

        Raises:
            aiohttp.ClientError: If HTTP request fails

        Requirements: 16.1, 16.3, 16.4, 16.5

        """
        _LOGGER.debug("Fetching alerts from NWS API")

        try:
            params = self._build_area_params(config)

            data = await self._fetch_json(
                session,
                self.API_URL,
                headers=self._HEADERS,
                params=params or None,
                timeout=DEFAULT_FETCH_TIMEOUT,
            )
            if data is None:
                return []

            _LOGGER.debug("Successfully fetched NWS API response")

            # Get features (alerts)
            features = data.get("features", [])

            _LOGGER.debug("Found %d features in NWS response", len(features))

            # Parse each feature into an Alert
            alerts = []
            for feature in features:
                alert = self._parse_alert(feature)
                if alert:
                    alerts.append(alert)

            _LOGGER.debug("Parsed %d alerts from NWS", len(alerts))

            return self._apply_location_filter(alerts, config)

        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP error fetching NWS alerts: %s", err)
            raise

    def _parse_alert(self, feature: dict) -> Alert | None:
        """Parse a single NWS alert from API feature.

        Args:
            feature: Feature dictionary from NWS API

        Returns:
            Alert object or None if parsing fails

        Requirements: 16.3, 16.4, 16.5, 16.6

        """
        try:
            properties = feature.get("properties", {})

            # Extract required fields
            alert_id = properties.get("id", "")
            event = properties.get("event", "Unknown")
            severity = properties.get("severity", "Unknown")
            headline = properties.get("headline", "")
            description = properties.get("description", "")
            instruction = properties.get("instruction", "")
            onset = properties.get("onset", "")
            ends = properties.get("ends", "")
            expires = properties.get("expires", "")
            area_desc = properties.get("areaDesc", "")

            if not alert_id:
                _LOGGER.warning("Skipping alert with empty ID")
                return None

            # Use ends if available, otherwise use expires
            end_time = ends or expires

            # NWS feed sends capitalised CAP severities (Minor/Moderate/Severe/Extreme).
            severity_name, level = resolve_severity(severity)

            # Classify event into alert type
            alert_type = self._classify_event(event)

            # Parse locations from areaDesc
            # Format: "San Diego County Coastal Areas; Orange County Coastal"
            locations = [loc.strip() for loc in area_desc.split(";") if loc.strip()]
            if not locations:
                locations = ["Unknown"]

            # Build full description
            full_description = description
            if instruction:
                full_description += f"\n\nInstructions: {instruction}"

            # Create alert
            alert = Alert(
                alert_id=f"nws_{compute_alert_id('nws', alert_id)}",
                source="nws",
                alert_type=alert_type,
                severity=severity_name,
                level=level,
                start_time=onset or utcnow().isoformat(),
                end_time=end_time,  # empty = "until further notice"
                locations=tuple(locations),
                summary=headline or event,
                description=full_description,
                link=f"https://api.weather.gov/alerts/{alert_id}" if alert_id else "",
                icon=get_icon_for_alert_type(alert_type),
                color=get_color_for_level(level),
            )

            _LOGGER.debug(
                "Parsed alert: %s (%s, level %d) for %s",
                event,
                severity_name,
                level,
                ", ".join(locations[:2]) + ("..." if len(locations) > 2 else ""),
            )

            return alert

        except Exception as err:
            _LOGGER.exception("Error parsing NWS alert: %s", err)
            return None

    # Walked top-to-bottom, first match wins. Specific cold/ice/snow rows
    # sit above the generic rain/wind rows so a compound event keeps its
    # specific type: "Wind Chill" stays cold, "Freezing Rain" stays ice.
    _CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("tornado", ("tornado",)),
        ("flood", ("flood", "flash flood", "storm surge")),
        ("fire", ("fire weather", "red flag", "wildfire", "smoke")),
        ("coastal", ("surf", "beach", "rip current", "coastal", "marine", "small craft")),
        ("avalanche", ("avalanche",)),
        ("wind", ("hurricane", "tropical storm", "typhoon")),
        ("snow", ("snow", "blizzard", "winter storm", "winter weather")),
        ("ice", ("ice", "freezing", "sleet", "frost", "spray")),
        ("cold", ("cold", "freeze", "wind chill", "chill")),
        ("heat", ("heat", "hot", "excessive heat")),
        ("rain", ("rain", "shower", "precipitation")),
        # Dust/sand storms grouped with wind (no dedicated dust type).
        ("wind", ("wind", "gale", "high wind", "dust", "sand")),
        ("fog", ("fog",)),
        ("thunderstorm", ("thunder", "lightning", "severe thunderstorm", "storm watch")),
        ("fog", ("air quality", "air stagnation")),
    )

    @classmethod
    def _classify_event(cls, event: str) -> str:
        """Classify NWS event into alert type.

        Args:
            event: NWS event name

        Returns:
            Alert type string

        Requirements: 16.4

        """
        return classify_by_keywords(event, cls._CLASSIFY_TABLE)

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing API access.

        Args:
            session: aiohttp client session
            config: Configuration to validate

        Returns:
            Tuple of (success, error_message)

        Requirements: 12.1, 12.2

        """
        return await self._validate_http_access(
            session, self.API_URL,
            params=self._build_area_params(config),
            headers=self._HEADERS,
        )

    @staticmethod
    def _build_area_params(config: dict[str, Any]) -> dict[str, str] | None:
        """Build the ``area`` query params for a state selection.

        The API takes ``area`` as a comma-separated list; a repeated
        ``area=`` parameter would keep only the last value.

        Args:
            config: Source configuration.

        Returns:
            ``{"area": "CA,NV"}``, or ``None`` for no state selected.

        """
        states = _as_list(config.get("state"))
        if not states:
            return None
        return {"area": ",".join(states)}

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for this source.

        Returns:
            Voluptuous schema for configuration

        Requirements: 11.3, 12.1

        """
        return common_config_schema(extra={
            # default=[] keeps the field clearable: without it an empty
            # submit omits the key and the options merge restores the old
            # value. _as_list first, so an entry that stored a single
            # string before this became multi-select still validates.
            vol.Optional("state", default=[]): vol.All(
                _as_list,
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(self.US_STATES),
                        multiple=True,
                    ),
                ),
            ),
        })
