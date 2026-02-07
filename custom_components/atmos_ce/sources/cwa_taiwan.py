"""CWA Taiwan weather warning source.

This module implements the CWA (Central Weather Administration) Taiwan
weather warning source plugin, which fetches alerts from the CWA Open Data
API (W-C0033-001).

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

import aiohttp
import voluptuous as vol
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from ..models import Alert, get_color_for_level, get_icon_for_alert_type
from ..source_base import (
    DEFAULT_FETCH_TIMEOUT,
    WeatherWarningSource,
    classify_by_keywords,
    common_config_schema,
    compute_alert_id,
)

_LOGGER = logging.getLogger(__name__)

# Taiwan counties/cities (22 total)
TAIWAN_COUNTIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣",
    "金門縣", "連江縣",
]


class CWATaiwanSource(WeatherWarningSource):
    """CWA Taiwan weather warnings source.

    This source fetches weather warnings from the CWA Open Data API.
    It supports typhoon, heavy rain, strong wind, cold, heat,
    thunderstorm, and fog alert types with county-level filtering
    for all 22 Taiwan counties and cities.

    Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
    """

    API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-001"

    @property
    def source_id(self) -> str:
        """Return unique source identifier."""
        return "cwa_taiwan"

    @property
    def source_name(self) -> str:
        """Return human-readable source name."""
        return "CWA Taiwan"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from CWA Taiwan API.

        Args:
            session: aiohttp client session.
            config: Source configuration containing api_key and optional counties.

        Returns:
            List of Alert objects parsed from the API response.

        """
        api_key = config.get("api_key")
        if not api_key:
            # Auth failure (not a transient error) so HA prompts for reauth.
            raise ConfigEntryAuthFailed("CWA Taiwan API key not configured")

        # Pass the key as an Authorization header rather than a query
        # parameter so it does not end up in aiohttp debug logs or any
        # reverse-proxy access log between HA and CWA. The API accepts
        # the key either way.
        data = await self._fetch_json(
            session, self.API_URL,
            headers={"Authorization": api_key},
            timeout=DEFAULT_FETCH_TIMEOUT,
        )
        if data is None:
            return []

        if data.get("success") != "true":
            # CWA returns HTTP 200 with success="false" for a rejected key
            # rather than a 401, so the auth failure has to be raised here.
            raise ConfigEntryAuthFailed(
                "CWA Taiwan API rejected the key (success=false)",
            )

        locations = data.get("records", {}).get("location", [])
        if not locations:
            _LOGGER.debug("No locations found in CWA Taiwan response")
            return []

        counties = config.get("counties", [])
        alerts = []
        skipped = 0
        for location in locations:
            # Guard each element so one malformed location only loses its
            # own alerts rather than the whole country's.
            try:
                location_name = location.get("locationName", "")
                hazards = location.get("hazardConditions", {}).get("hazards", [])

                # Filter by counties if configured
                if counties and location_name not in counties:
                    continue

                for hazard in hazards:
                    alert = self._parse_alert(hazard, location_name)
                    if alert:
                        alerts.append(alert)
            except (AttributeError, TypeError) as err:
                skipped += 1
                _LOGGER.warning("Skipped malformed CWA Taiwan location: %s", err)
                continue

        if skipped:
            _LOGGER.info(
                "CWA Taiwan: parsed %d alerts, skipped %d malformed locations",
                len(alerts), skipped,
            )
        else:
            _LOGGER.debug("Fetched %d alerts from CWA Taiwan", len(alerts))
        return self._apply_location_filter(alerts, config)

    def _parse_alert(self, hazard: dict, location_name: str) -> Alert | None:
        """Parse a single CWA Taiwan alert from hazard data.

        Args:
            hazard: Hazard dictionary from the API response.
            location_name: Name of the location (county/city).

        Returns:
            Alert object or None if parsing fails.

        """
        try:
            info = hazard.get("info", {})
            valid_time = hazard.get("validTime", {})

            phenomena = info.get("phenomena", "")
            significance = info.get("significance", "")
            start_time = valid_time.get("startTime", "")
            end_time = valid_time.get("endTime", "")

            if not phenomena or not start_time or not end_time:
                return None

            # Classify alert type
            alert_type = self._classify_phenomena(phenomena)

            # Map significance to severity level
            # CWA uses: 特報 (advisory), 警報 (warning), 嚴重特報 (severe warning)
            level = self._map_significance_to_level(significance, phenomena)

            # Generate alert ID
            alert_id = f"cwa_taiwan_{compute_alert_id('cwa_taiwan', f'{location_name}|{phenomena}|{start_time}')}"

            # Format times to ISO 8601
            start_iso = start_time.replace(" ", "T") + "+08:00"
            end_iso = end_time.replace(" ", "T") + "+08:00"

            return Alert(
                alert_id=alert_id,
                source="cwa_taiwan",
                alert_type=alert_type,
                severity=self._get_severity_name(level),
                level=level,
                start_time=start_iso,
                end_time=end_iso,
                locations=(location_name,),
                summary=f"{phenomena}{significance}",
                description=f"{location_name} {phenomena}{significance}",
                link=f"https://www.cwa.gov.tw/V8/C/P/Warning/W{self._get_warning_code(phenomena)}.html",
                icon=get_icon_for_alert_type(alert_type),
                color=get_color_for_level(level),
            )
        except Exception as err:
            _LOGGER.error("Error parsing CWA Taiwan alert: %s", err)
            return None

    # Phenomena-keyword classification table, walked in order, first
    # match wins. Chinese keywords are unaffected by the case-fold in
    # ``classify_by_keywords``; "typhoon" is kept lowercase so the
    # English alias still matches the folded text.
    _CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("flood", ("水災", "洪水", "淹水")),
        ("coastal", ("海嘯", "海岸")),
        ("wind", ("颱風", "typhoon")),
        ("rain", ("豪雨", "大雨", "雨量")),
        ("wind", ("強風", "風力")),
        ("cold", ("低溫", "寒流", "冷氣團")),
        ("heat", ("高溫", "熱浪")),
        ("thunderstorm", ("雷雨", "雷暴")),
        ("fog", ("濃霧",)),
    )

    @classmethod
    def _classify_phenomena(cls, phenomena: str) -> str:
        """Classify CWA phenomena string into a normalised alert type.

        Args:
            phenomena: Chinese phenomena string from the API (e.g. "颱風", "豪雨").

        Returns:
            Normalised alert type string (e.g. "wind", "rain", "unknown").

        """
        return classify_by_keywords(phenomena, cls._CLASSIFY_TABLE)

    @staticmethod
    def _map_significance_to_level(significance: str, phenomena: str) -> int:
        """Map CWA significance and phenomena to a numeric severity level.

        CWA uses 特報 (advisory), 警報 (warning), and 嚴重特報 (severe warning).
        Typhoons and rain warnings have specialised mappings.

        Args:
            significance: Chinese significance string (e.g. "特報", "警報").
            phenomena: Chinese phenomena string for context-dependent mapping.

        Returns:
            Numeric severity level from 1 (lowest) to 4 (highest).

        """
        # For typhoons, use special mapping
        if "颱風" in phenomena:
            if "海上" in significance:
                return 2  # Sea warning
            if "陸上" in significance:
                return 3  # Land warning
            return 2

        # For rain warnings
        if "豪雨" in phenomena or "雨" in phenomena:
            if "超大豪雨" in phenomena:
                return 4  # Extremely heavy rain
            if "大豪雨" in phenomena:
                return 3  # Heavy torrential rain
            if "豪雨" in phenomena:
                return 2  # Torrential rain

        # General mapping
        if "嚴重" in significance or "緊急" in significance:
            return 4
        if "警報" in significance:
            return 3
        if "特報" in significance:
            return 2
        return 1

    @staticmethod
    def _get_severity_name(level: int) -> str:
        """Map numeric severity level to a human-readable name.

        Args:
            level: Numeric severity level (1-4).

        Returns:
            Severity name string (advisory, watch, warning, or severe).

        """
        severity_map = {
            1: "advisory",
            2: "watch",
            3: "warning",
            4: "severe",
        }
        return severity_map.get(level, "advisory")

    @staticmethod
    def _get_warning_code(phenomena: str) -> str:
        """Map phenomena string to CWA warning page code.

        Args:
            phenomena: Chinese phenomena string.

        Returns:
            Two-digit warning code used in the CWA website URL.

        """
        if "颱風" in phenomena:
            return "21"
        if "豪雨" in phenomena or "大雨" in phenomena:
            return "28"
        if "強風" in phenomena:
            return "25"
        if "低溫" in phenomena or "寒流" in phenomena:
            return "26"
        if "高溫" in phenomena:
            return "37"
        return "00"

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing API access.

        Args:
            session: aiohttp client session.
            config: Configuration to validate (must contain api_key).

        Returns:
            Tuple of (success, error_message).

        """
        api_key = config.get("api_key")
        if not api_key:
            return False, "API key is required"

        try:
            response = await self._fetch_with_retry(
                session, self.API_URL,
                headers={"Authorization": api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            async with response:
                if response.status != 200:
                    return False, f"API returned HTTP {response.status}"
                data = await response.json()

                if data.get("success") != "true":
                    return False, "API returned unsuccessful response"

            return True, None
        except aiohttp.ClientError as err:
            return False, f"Failed to connect to CWA Taiwan API: {err}"
        except Exception as err:
            return False, f"Unexpected error: {err}"

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for this source.

        Returns:
            Voluptuous schema for CWA Taiwan configuration.

        """
        return common_config_schema(extra={
            vol.Required("api_key"): cv.string,
            vol.Optional("counties", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=TAIWAN_COUNTIES,
                    multiple=True,
                ),
            ),
        })
