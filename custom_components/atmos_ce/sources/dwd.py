"""Deutscher Wetterdienst (DWD) weather warning source (Germany).

This module implements the DWD weather warning source plugin,
which fetches alerts from the DWD WFS API.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6
"""
from __future__ import annotations

import json
import logging
from typing import Any, ClassVar, Final

import aiohttp
import voluptuous as vol
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
    classify_by_keywords,
    common_config_schema,
    compute_alert_id,
)

_LOGGER = logging.getLogger(__name__)

# Hard cap on DWD WFS response size. The full German municipality
# GeoJSON with multipolygon geometry can reach ~33 MB on an event-free
# day and grows under storm activity. Parsing 100+ MB of JSON on HA's
# event loop would stall the runtime; abort loudly instead.
_DWD_MAX_BYTES: Final = 50 * 1024 * 1024  # 50 MB

# German CAP-profile colours the DWD feed embeds as ``EC_AREA_COLOR``.
# When present, the colour is authoritative over the free-text severity
# string, DWD website renders from the same colour.
_DWD_COLOR_TO_LEVEL: Final[dict[str, tuple[str, int]]] = {
    "#ffeb3b": ("yellow", 2),
    "#fb8c00": ("orange", 3),
    "#e53935": ("red", 4),
    "#b71c1c": ("red", 4),  # darker red = still the top tier
}


class DWDSource(WeatherWarningSource):
    """Deutscher Wetterdienst weather warnings (Germany).

    This source fetches weather warnings from the DWD WFS API.
    It supports Minor, Moderate, Severe, and Extreme severity levels
    for various weather types.

    Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6
    """

    API_URL = "https://maps.dwd.de/geoserver/dwd/ows"

    @property
    def source_id(self) -> str:
        """Return the unique identifier for this source."""
        return "dwd"

    @property
    def source_name(self) -> str:
        """Return the human-readable name for this source."""
        return "Deutscher Wetterdienst"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from DWD WFS API.

        Args:
            session: aiohttp client session
            config: Source configuration

        Returns:
            List of Alert objects

        Raises:
            aiohttp.ClientError: If HTTP request fails

        Requirements: 19.1, 19.3, 19.4, 19.5

        """
        _LOGGER.debug("Fetching alerts from DWD WFS API")

        try:
            # Build WFS query params
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": "dwd:Warnungen_Gemeinden",
                "outputFormat": "application/json",
            }

            response = await self._fetch_with_retry(
                session,
                self.API_URL,
                params=params,
                timeout=DEFAULT_FETCH_TIMEOUT,
            )
            async with response:
                if response.status != 200:
                    _LOGGER.warning("DWD API returned HTTP %s", response.status)
                    return []
                # Early-abort on oversized payloads. DWD geometry alone
                # can balloon the response, parsing gigabytes of JSON on
                # the event loop would stall HA. Check Content-Length
                # when the server is honest, otherwise limit the read.
                content_length = response.content_length
                if content_length is not None and content_length > _DWD_MAX_BYTES:
                    _LOGGER.error(
                        "DWD response too large (%d bytes > %d); aborting",
                        content_length, _DWD_MAX_BYTES,
                    )
                    return []
                raw = await response.content.read(_DWD_MAX_BYTES + 1)
                if len(raw) > _DWD_MAX_BYTES:
                    _LOGGER.error(
                        "DWD response exceeded %d-byte cap; aborting",
                        _DWD_MAX_BYTES,
                    )
                    return []
            data = json.loads(raw)

            _LOGGER.debug("Successfully fetched DWD WFS API response")

            # Get features (alerts). Drop `geometry` eagerly, we never
            # consume it and each feature carries kilobytes of polygon
            # coordinates that only bloat memory.
            features = data.get("features", [])
            for feature in features:
                feature.pop("geometry", None)

            _LOGGER.debug("Found %d features in DWD response", len(features))

            # Parse each feature into an Alert
            alerts = []
            for feature in features:
                alert = self._parse_alert(feature)
                if alert:
                    alerts.append(alert)

            _LOGGER.debug("Parsed %d alerts from DWD", len(alerts))

            return self._apply_location_filter(alerts, config)

        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP error fetching DWD alerts: %s", err)
            raise

    def _parse_alert(self, feature: dict) -> Alert | None:
        """Parse a single DWD alert from WFS feature.

        Args:
            feature: Feature dictionary from DWD WFS API

        Returns:
            Alert object or None if parsing fails

        Requirements: 19.3, 19.4, 19.5, 19.6

        """
        try:
            properties = feature.get("properties", {})

            # Extract required fields
            identifier = properties.get("IDENTIFIER", "")
            event = properties.get("EVENT", "Unknown")
            severity = properties.get("SEVERITY", "Unknown")
            headline = properties.get("HEADLINE", "")
            description = properties.get("DESCRIPTION", "")
            instruction = properties.get("INSTRUCTION", "")
            onset = properties.get("ONSET", "")
            expires = properties.get("EXPIRES", "")
            area_desc = properties.get("AREADESC", "")
            name = properties.get("NAME", "")
            ec_group = properties.get("EC_GROUP", "")

            if not identifier:
                _LOGGER.warning("Skipping alert with empty IDENTIFIER")
                return None

            # Prefer EC_AREA_COLOR when present (authoritative per the
            # German CAP profile). Fall back to the free-text SEVERITY.
            ec_color = (properties.get("EC_AREA_COLOR") or "").lower()
            colour_info = _DWD_COLOR_TO_LEVEL.get(ec_color)
            if colour_info is not None:
                severity_name, level = colour_info
            else:
                severity_name, level = resolve_severity(severity)

            # Classify event into alert type using EC_GROUP
            alert_type = self._classify_event(ec_group, event)

            # Parse locations from AREADESC and NAME
            # AREADESC is short name, NAME is full name
            locations = []
            if area_desc:
                locations.append(area_desc)
            if name and name != area_desc:
                locations.append(name)
            if not locations:
                locations = ["Unknown"]

            # Build full description
            full_description = description
            if instruction:
                full_description += f"\n\n{instruction}"

            # Create alert
            alert = Alert(
                alert_id=f"dwd_{compute_alert_id('dwd', identifier)}",
                source="dwd",
                alert_type=alert_type,
                severity=severity_name,
                level=level,
                start_time=onset or utcnow().isoformat(),
                end_time=expires or "",  # empty = "until further notice"
                locations=tuple(locations),
                summary=headline or event,
                description=full_description,
                link=properties.get("WEB", "https://dwd.de/warnungen"),
                icon=get_icon_for_alert_type(alert_type),
                color=get_color_for_level(level),
            )

            _LOGGER.debug(
                "Parsed alert: %s (%s, level %d) for %s",
                event,
                severity,
                level,
                ", ".join(locations[:2]) + ("..." if len(locations) > 2 else ""),
            )

            return alert

        except Exception as err:
            _LOGGER.exception("Error parsing DWD alert: %s", err)
            return None

    # EC_GROUP classification table (preferred, more reliable). Walked
    # in order, first match wins.
    _GROUP_CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("flood", ("flood", "hochwasser")),
        ("fire", ("forest_fire", "waldbrand")),
        ("avalanche", ("avalanche", "lawine")),
        ("thunderstorm", ("thunderstorm", "lightning")),
        ("cold", ("frost", "cold")),
        ("ice", ("slipperiness", "black_ice")),
        ("snow", ("snowfall", "snow")),
        ("rain", ("rain", "heavy_rain")),
        ("wind", ("wind", "gale", "storm")),
        ("fog", ("fog",)),
        ("heat", ("heat",)),
    )

    # EVENT fallback table (German free-text). Used only when EC_GROUP
    # yields no match.
    _EVENT_CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("flood", ("hochwasser", "überschwemmung")),
        ("fire", ("waldbrand", "feuer")),
        ("avalanche", ("lawine",)),
        ("cold", ("frost", "kälte")),
        ("ice", ("glätte", "glatteis")),
        ("snow", ("schnee", "schneef")),
        ("rain", ("regen", "niederschlag")),
        ("wind", ("wind", "sturm", "orkan")),
        ("fog", ("nebel",)),
        ("thunderstorm", ("gewitter", "blitz")),
        ("heat", ("hitze",)),
    )

    @classmethod
    def _classify_event(cls, ec_group: str, event: str) -> str:
        """Classify DWD event into alert type.

        Prefers the EC_GROUP field (more reliable); falls back to the
        free-text EVENT field when EC_GROUP yields no match.

        Args:
            ec_group: DWD EC_GROUP field (e.g., "SNOWFALL", "FROST")
            event: DWD EVENT field (fallback)

        Returns:
            Alert type string

        Requirements: 19.4

        """
        # Sentinel lets an EC_GROUP miss fall through to the EVENT table.
        group_match = classify_by_keywords(
            ec_group, cls._GROUP_CLASSIFY_TABLE, default="",
        )
        if group_match:
            return group_match
        return classify_by_keywords(event, cls._EVENT_CLASSIFY_TABLE)

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
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": "dwd:Warnungen_Gemeinden",
            "outputFormat": "application/json",
            "count": "1",
        }
        return await self._validate_http_access(
            session, self.API_URL, params=params,
        )

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for this source.

        Returns:
            Voluptuous schema for configuration

        Requirements: 11.3, 12.1

        """
        return common_config_schema()
