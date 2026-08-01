"""Environment Canada weather warnings source (Canada).

This module implements the Environment Canada weather warning source plugin,
which fetches alerts from the Environment Canada CAP XML feeds hosted on
the Meteorological Service of Canada Datamart.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
"""
from __future__ import annotations

import asyncio
import logging
import re
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
    async_parse_xml,
    classify_by_keywords,
    common_config_schema,
    compute_alert_id,
)

_LOGGER = logging.getLogger(__name__)


class EnvironmentCanadaSource(WeatherWarningSource):
    """Environment Canada weather warnings (Canada via CAP XML feeds).

    This source fetches weather warnings from the Environment Canada
    Datamart CAP XML feeds. It discovers office codes from a directory
    listing, then fetches individual CAP files concurrently with a
    semaphore to avoid overwhelming the server.

    Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
    """

    BASE_URL = "https://dd.weather.gc.ca/today/alerts/cap"
    _MAX_CONCURRENT_REQUESTS = 10

    # Supported provinces/territories
    SUPPORTED_PROVINCES: ClassVar[dict[str, str]] = {
        "AB": "Alberta",
        "BC": "British Columbia",
        "MB": "Manitoba",
        "NB": "New Brunswick",
        "NL": "Newfoundland and Labrador",
        "NS": "Nova Scotia",
        "NT": "Northwest Territories",
        "NU": "Nunavut",
        "ON": "Ontario",
        "PE": "Prince Edward Island",
        "QC": "Quebec",
        "SK": "Saskatchewan",
        "YT": "Yukon",
    }

    @property
    def source_id(self) -> str:
        """Return unique identifier for this source."""
        return "environment_canada"

    @property
    def source_name(self) -> str:
        """Return human-readable name."""
        return "Environment Canada"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from Environment Canada CAP XML feeds.

        Discovers office codes from the daily directory listing, then
        fetches all CAP files concurrently (bounded by a semaphore) to
        avoid an N+1 sequential HTTP request storm.

        Args:
            session: aiohttp client session.
            config: Source configuration containing provinces list.

        Returns:
            List of Alert objects from all discovered CAP files.

        """
        provinces = _as_list(config.get("provinces", ["ON"]))

        # Get today's date for directory path
        today = utcnow().strftime("%Y%m%d")
        base_url = f"{self.BASE_URL}/{today}/"

        # Phase 1: Fetch directory listing to find office codes
        try:
            response = await self._fetch_with_retry(
                session, base_url, timeout=DEFAULT_FETCH_TIMEOUT,
            )
            async with response:
                if response.status != 200:
                    _LOGGER.warning("Environment Canada returned HTTP %s", response.status)
                    return []
                html = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error fetching Environment Canada directory: %s", err)
            return []

        office_codes = re.findall(r'href="([A-Z]{4})/"', html)
        _LOGGER.debug("Found %d office codes: %s", len(office_codes), office_codes)

        if not office_codes:
            return []

        # Phase 2: Fetch office listings concurrently to collect CAP URLs
        semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_REQUESTS)
        cap_urls: list[str] = []

        async def _fetch_office_listing(office: str) -> list[str]:
            """Fetch CAP file URLs from a single office listing."""
            office_url = f"{base_url}{office}/00/"
            async with semaphore:
                try:
                    resp = await self._fetch_with_retry(
                        session, office_url, timeout=DEFAULT_FETCH_TIMEOUT,
                    )
                    async with resp:
                        office_html = await resp.text()
                    cap_files = re.findall(r'href="([^"]+\.cap)"', office_html)
                    _LOGGER.debug("Office %s: %d CAP files", office, len(cap_files))
                    return [f"{office_url}{cap_file}" for cap_file in cap_files]
                except Exception as err:
                    _LOGGER.warning("Error fetching office %s: %s", office, err)
                    return []

        office_results = await asyncio.gather(
            *(_fetch_office_listing(office) for office in office_codes),
            return_exceptions=True,
        )

        for result in office_results:
            if isinstance(result, BaseException):
                _LOGGER.warning("Office listing task failed: %s", result)
                continue
            cap_urls.extend(result)

        _LOGGER.debug("Total CAP URLs to fetch: %d", len(cap_urls))

        if not cap_urls:
            return []

        # Phase 3: Fetch and parse all CAP files concurrently
        async def _fetch_cap(url: str) -> Alert | None:
            """Fetch and parse a single CAP XML file."""
            async with semaphore:
                try:
                    cap_resp = await self._fetch_with_retry(
                        session, url, timeout=DEFAULT_FETCH_TIMEOUT,
                    )
                    async with cap_resp:
                        xml_text = await cap_resp.text()
                    # Offload XML parse so many concurrent CAP files don't
                    # serialize on the event loop.
                    data = await async_parse_xml(xml_text)
                    return self._parse_alert(data, provinces)
                except Exception as err:
                    _LOGGER.warning("Error fetching CAP file %s: %s", url, err)
                    return None

        cap_results = await asyncio.gather(
            *(_fetch_cap(url) for url in cap_urls),
            return_exceptions=True,
        )

        all_alerts: list[Alert] = []
        for result in cap_results:
            if isinstance(result, BaseException):
                _LOGGER.warning("CAP fetch task failed: %s", result)
                continue
            if result is not None:
                all_alerts.append(result)

        _LOGGER.debug("Fetched %d total alerts from Environment Canada", len(all_alerts))
        return self._apply_location_filter(all_alerts, config)

    def _parse_alert(self, data: dict, provinces: list[str]) -> Alert | None:
        """Parse a single Environment Canada CAP alert.

        Args:
            data: Parsed CAP XML dictionary from xmltodict.
            provinces: List of province codes to filter by.

        Returns:
            Alert object or None if parsing fails or province doesn't match.

        """
        try:
            alert_data = data.get("alert", {})
            info = alert_data.get("info", {})

            # Handle multiple info blocks (bilingual alerts)
            if isinstance(info, list):
                # Prefer English info block
                for i in info:
                    if i.get("language", "").startswith("en"):
                        info = i
                        break
                else:
                    info = info[0]

            # Extract basic fields
            alert_id = alert_data.get("identifier", "")
            sent = alert_data.get("sent", "")
            event = info.get("event", "Unknown")
            severity = info.get("severity", "Minor")
            urgency = info.get("urgency", "Unknown")
            headline = info.get("headline", "")
            description = info.get("description", "")
            instruction = info.get("instruction", "")
            effective = info.get("effective", sent)
            onset = info.get("onset", effective)
            expires = info.get("expires", "")
            web = info.get("web", "https://weather.gc.ca/")

            # Extract area information
            area = info.get("area", {})
            if isinstance(area, list):
                area = area[0] if area else {}

            area_desc = area.get("areaDesc", "Unknown")

            # Check if alert is for selected provinces
            if provinces:
                # Check if any selected province is mentioned in area description
                province_match = False
                for prov_code in provinces:
                    prov_name = self.SUPPORTED_PROVINCES.get(prov_code, "")
                    if prov_name.lower() in area_desc.lower():
                        province_match = True
                        break

                if not province_match:
                    return None

            # Extract alert type and color from parameters
            alert_name_param = None

            parameters = _as_list(info.get("parameter", []))

            for param in parameters:
                value_name = param.get("valueName", "")
                if "Alert_Name" in value_name:
                    alert_name_param = param.get("value", "")

            # Classify event type
            alert_type = self._classify_event(event)

            # Map severity to level and extract color
            severity_name, level = self._map_severity(severity, urgency, alert_name_param)

            # Parse locations
            locations = [area_desc] if area_desc else []

            # Combine description and instruction
            full_description = description
            if instruction:
                full_description = f"{description}\n\n{instruction}"

            return Alert(
                alert_id=f"environment_canada_{compute_alert_id('environment_canada', alert_id)}",
                source="environment_canada",
                alert_type=alert_type,
                severity=severity_name,
                level=level,
                start_time=onset,
                end_time=expires or onset,
                locations=tuple(locations),
                summary=headline,
                description=full_description,
                link=web,
                icon=get_icon_for_alert_type(alert_type),
                color=get_color_for_level(level),
            )

        except Exception as err:
            _LOGGER.warning("Error parsing Environment Canada alert: %s", err)
            return None

    # Walked in order, first match wins. Specific cold/ice/snow rows sit
    # above the generic rain/wind rows so a compound event keeps its
    # specific type: "Freezing Rain" stays ice, "Wind Chill" stays cold.
    _CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("tornado", ("tornado",)),
        ("flood", ("flood", "flooding", "flash flood", "storm surge")),
        ("fire", ("wildfire", "fire weather", "forest fire")),
        ("coastal", ("coastal", "marine", "surf", "rip current")),
        ("avalanche", ("avalanche",)),
        ("wind", ("hurricane", "tropical")),
        ("snow", (
            "snow", "blizzard", "winter storm", "snowfall", "blowing snow", "poudrerie",
        )),
        ("ice", ("ice", "freezing", "frost")),
        # "arctic outflow" is BC's cold-wind warning.
        ("cold", ("cold", "freeze", "chill", "arctic outflow", "arctic")),
        ("heat", ("heat", "hot")),
        ("rain", ("rain", "rainfall")),
        ("wind", ("wind", "gale")),
        ("fog", ("fog", "visibility")),
        ("thunderstorm", ("thunder", "lightning", "storm")),
    )

    @classmethod
    def _classify_event(cls, event: str) -> str:
        """Classify an Environment Canada event string into a normalised alert type.

        Args:
            event: Event string from the CAP XML (e.g. "Rainfall", "Blizzard").

        Returns:
            Normalised alert type string (e.g. "rain", "wind", "unknown").

        """
        return classify_by_keywords(event, cls._CLASSIFY_TABLE)

    @staticmethod
    def _map_severity(severity: str, urgency: str, alert_name: str | None) -> tuple[str, int]:
        """Map CAP severity and urgency to a colour-coded severity name and level.

        The colour override from ``alert_name`` (EN or FR) always wins;
        otherwise the shared :data:`source_base.SEVERITY_MAP` resolves the
        CAP severity. ``urgency == "Immediate"`` escalates a borderline
        level-2 or level-3 result by one tier, capped at 4, mirroring
        how NOAA and Meteoalarm clients surface imminent alerts.

        Args:
            severity: CAP severity string (e.g. "Extreme", "Severe").
            urgency: CAP urgency string ("Immediate" triggers escalation).
            alert_name: Optional Alert_Name parameter with colour info.

        Returns:
            Tuple of (severity_name, numeric_level).

        """
        if alert_name:
            alert_name_lower = alert_name.lower()
            if "red" in alert_name_lower or "rouge" in alert_name_lower:
                return "red", 4
            if "orange" in alert_name_lower:
                return "orange", 3
            if "yellow" in alert_name_lower or "jaune" in alert_name_lower:
                return "yellow", 2

        severity_name, level = resolve_severity(severity)

        # Urgency escalation: "Immediate" bumps borderline alerts up one
        # tier; "Expected" / "Future" / "Past" are left unchanged.
        if urgency == "Immediate" and 2 <= level <= 3:
            level += 1
            severity_name = {3: "orange", 4: "red"}[level]

        return severity_name, level

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing feed access.

        Args:
            session: aiohttp client session.
            config: Configuration to validate (must contain provinces list).

        Returns:
            Tuple of (success, error_message).

        """
        valid, error = self._validate_list_selection(
            config, "provinces", self.SUPPORTED_PROVINCES,
            singular="province", plural="provinces",
        )
        if not valid:
            return False, error

        today = utcnow().strftime("%Y%m%d")
        url = f"{self.BASE_URL}/{today}/"
        return await self._validate_http_access(session, url)

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for Environment Canada.

        Returns:
            Voluptuous schema for Environment Canada configuration.

        """
        province_options = dict(self.SUPPORTED_PROVINCES)

        return common_config_schema(extra={
            vol.Required("provinces", default=["ON"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    # HA's SelectSelectorConfig.options stub wants
                    # Sequence[SelectOptionDict]; a plain dict literal is
                    # accepted at runtime but mypy can't match it.
                    options=[{"label": v, "value": k} for k, v in province_options.items()],  # type: ignore[typeddict-item]
                    multiple=True,
                ),
            ),
        })
