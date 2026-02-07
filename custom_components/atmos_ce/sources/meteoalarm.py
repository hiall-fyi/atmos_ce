"""Meteoalarm weather warnings source (Europe).

This module implements the Meteoalarm weather warning source plugin,
which fetches alerts from the Meteoalarm legacy Atom feeds covering
40 European countries.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

import aiohttp
import voluptuous as vol
from homeassistant.helpers import selector

from ..models import Alert, get_color_for_level, get_icon_for_alert_type
from ..source_base import (
    DEFAULT_FETCH_TIMEOUT,
    SEVERITY_MAP,
    WeatherWarningSource,
    _as_list,
    async_parse_xml,
    classify_by_keywords,
    common_config_schema,
    compute_alert_id,
)

_LOGGER = logging.getLogger(__name__)


class MeteoalarmSource(WeatherWarningSource):
    """Meteoalarm weather warnings (Europe via legacy Atom feeds).

    This source fetches weather warnings from the Meteoalarm legacy Atom
    feeds. It supports 40 European countries and classifies alerts into
    standard types (rain, wind, snow, fog, thunderstorm, heat, cold)
    with yellow/orange/red severity levels.

    Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
    """

    FEED_URL_TEMPLATE = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{country}"
    _MAX_CONCURRENT_REQUESTS = 5

    # Supported countries (from feeds.meteoalarm.org)
    SUPPORTED_COUNTRIES: ClassVar[dict[str, str]] = {
        "andorra": "Andorra",
        "austria": "Austria",
        "belgium": "Belgium",
        "bosnia-herzegovina": "Bosnia and Herzegovina",
        "bulgaria": "Bulgaria",
        "croatia": "Croatia",
        "cyprus": "Cyprus",
        "czechia": "Czech Republic",
        "denmark": "Denmark",
        "estonia": "Estonia",
        "finland": "Finland",
        "france": "France",
        "germany": "Germany",
        "greece": "Greece",
        "hungary": "Hungary",
        "iceland": "Iceland",
        "ireland": "Ireland",
        "israel": "Israel",
        "italy": "Italy",
        "latvia": "Latvia",
        "lithuania": "Lithuania",
        "luxembourg": "Luxembourg",
        "malta": "Malta",
        "moldova": "Moldova",
        "montenegro": "Montenegro",
        "netherlands": "Netherlands",
        "republic-of-north-macedonia": "North Macedonia",
        "norway": "Norway",
        "poland": "Poland",
        "portugal": "Portugal",
        "romania": "Romania",
        "serbia": "Serbia",
        "slovakia": "Slovakia",
        "slovenia": "Slovenia",
        "spain": "Spain",
        "sweden": "Sweden",
        "switzerland": "Switzerland",
        "ukraine": "Ukraine",
        "united-kingdom": "United Kingdom",
    }

    @property
    def source_id(self) -> str:
        """Return unique identifier for this source."""
        return "meteoalarm"

    @property
    def source_name(self) -> str:
        """Return human-readable name."""
        return "Meteoalarm"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from Meteoalarm Atom feeds for selected countries.

        Fetches all selected countries concurrently with a semaphore to
        avoid overwhelming the server.

        Args:
            session: aiohttp client session.
            config: Source configuration containing countries list.

        Returns:
            List of Alert objects from all selected countries.

        """
        countries = _as_list(config.get("countries", ["united-kingdom"]))

        semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_REQUESTS)

        async def _fetch_country(country: str) -> list[Alert]:
            """Fetch alerts for a single country."""
            async with semaphore:
                try:
                    url = self.FEED_URL_TEMPLATE.format(country=country)

                    response = await self._fetch_with_retry(
                        session, url, timeout=DEFAULT_FETCH_TIMEOUT,
                    )
                    async with response:
                        if response.status != 200:
                            _LOGGER.warning("MeteoAlarm %s returned HTTP %s", country, response.status)
                            return []
                        xml_text = await response.text()

                    # Parse Atom feed off the event loop with entity expansion disabled.
                    data = await async_parse_xml(xml_text)
                    feed = data.get("feed", {})
                    entries = feed.get("entry", [])

                    entries = _as_list(entries)

                    # Parse each entry. A single malformed entry must not
                    # drop the rest of the country's alerts, the
                    # meteoalarm feed mixes CAP and bespoke fields and
                    # occasionally emits garbage for one entry while
                    # surrounding entries are valid.
                    alerts: list[Alert] = []
                    skipped = 0
                    for entry in entries:
                        try:
                            alert = self._parse_alert(entry, country)
                            if alert:
                                alerts.append(alert)
                        except Exception as err:
                            skipped += 1
                            _LOGGER.warning(
                                "Skipped Meteoalarm entry from %s: %s",
                                country, err,
                            )
                            continue

                    if skipped:
                        _LOGGER.info(
                            "Meteoalarm %s: parsed %d alerts, skipped %d "
                            "malformed entries",
                            country, len(alerts), skipped,
                        )
                    else:
                        _LOGGER.debug(
                            "Fetched %d alerts from Meteoalarm (%s)",
                            len(alerts), country,
                        )
                    return alerts

                except Exception as err:
                    _LOGGER.error("Error fetching Meteoalarm feed for %s: %s", country, err)
                    return []

        results = await asyncio.gather(
            *(_fetch_country(country) for country in countries),
            return_exceptions=True,
        )

        all_alerts: list[Alert] = []
        for result in results:
            if isinstance(result, BaseException):
                _LOGGER.warning("Meteoalarm country fetch failed: %s", result)
                continue
            all_alerts.extend(result)

        _LOGGER.debug("Fetched %d total alerts from Meteoalarm (%d countries)", len(all_alerts), len(countries))
        return self._apply_location_filter(all_alerts, config)

    def _parse_alert(self, entry: dict, country: str) -> Alert | None:
        """Parse a single Meteoalarm Atom entry into an Alert.

        Args:
            entry: Atom feed entry dictionary from xmltodict.
            country: Country slug used to fetch this entry.

        Returns:
            Alert object or None if parsing fails.

        """
        # Extract CAP fields (with namespace prefix)
        cap_ns = "cap:"

        # Get basic fields
        title = entry.get("title", "")
        alert_id = entry.get("id", "")
        updated = entry.get("updated", "")

        # Extract CAP fields
        event = entry.get(f"{cap_ns}event", "Unknown")
        severity = entry.get(f"{cap_ns}severity", "Minor")
        area_desc = entry.get(f"{cap_ns}areaDesc", "")
        onset = entry.get(f"{cap_ns}onset", "")
        expires = entry.get(f"{cap_ns}expires", "")

        # Extract link to full CAP XML
        links = _as_list(entry.get("link", []))

        cap_link = ""
        for link in links:
            if isinstance(link, dict) and link.get("@type") == "application/cap+xml":
                cap_link = link.get("@href", "")
                break

        # Classify event type
        alert_type = self._classify_event(event)

        # Severity precedence: title colour keyword wins over CAP severity
        # (Meteoalarm titles reliably contain Yellow/Orange/Red; CAP
        # severity field is looser). Fall back to the shared CAP table
        # when no colour is in the title. Default is (yellow, level 2)
        # which matches the shared SEVERITY_MAP.
        severity_name = "yellow"
        level = SEVERITY_MAP["yellow"]
        title_lower = title.lower()
        for colour in ("red", "orange", "yellow"):
            if colour in title_lower:
                severity_name = colour
                level = SEVERITY_MAP[colour]
                break
        else:
            # No colour in the title, use CAP severity as provided.
            severity_name = severity.lower() or severity_name
            level = SEVERITY_MAP.get(severity_name, level)

        # Parse locations
        locations = [area_desc] if area_desc else []

        # Use onset as start time, expires as end time
        start_time = onset or updated
        end_time = expires or updated

        return Alert(
            alert_id=f"meteoalarm_{compute_alert_id('meteoalarm', alert_id)}",
            source="meteoalarm",
            alert_type=alert_type,
            severity=severity_name,
            level=level,
            start_time=start_time,
            end_time=end_time,
            locations=tuple(locations),
            summary=title,
            description=f"{event} - {area_desc}",
            link=cap_link or "https://meteoalarm.org",
            icon=get_icon_for_alert_type(alert_type),
            color=get_color_for_level(level),
        )

    # Event-keyword classification table, walked in order, first match
    # wins (specific before generic).
    _CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("tornado", ("tornado",)),
        ("flood", ("flood", "flash flood", "storm surge")),
        ("fire", ("forest-fire", "forestfire", "forest fire", "wildfire")),
        ("coastal", ("coastal",)),
        ("avalanche", ("avalanche",)),
        # The live CAP feed emits spaced awareness types ("high
        # temperature"); hyphenated/concatenated forms are kept as aliases.
        ("heat", ("heat", "high temperature", "high-temperature", "hightemperature")),
        ("cold", (
            "cold", "low temperature", "low-temperature", "lowtemperature", "freeze",
        )),
        ("snow", ("snow", "ice")),
        ("rain", ("rain",)),
        ("wind", ("wind",)),
        ("fog", ("fog",)),
        ("thunderstorm", ("thunder", "lightning")),
    )

    @classmethod
    def _classify_event(cls, event: str) -> str:
        """Classify a Meteoalarm CAP event string into a normalised alert type.

        Args:
            event: Event string from the CAP profile (e.g. "Wind", "Thunderstorm").

        Returns:
            Normalised alert type string (e.g. "wind", "rain", "unknown").

        """
        return classify_by_keywords(event, cls._CLASSIFY_TABLE)

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing feed access.

        Args:
            session: aiohttp client session.
            config: Configuration to validate (must contain countries list).

        Returns:
            Tuple of (success, error_message).

        """
        valid, error = self._validate_list_selection(
            config, "countries", self.SUPPORTED_COUNTRIES,
            singular="country", plural="countries",
        )
        if not valid:
            return False, error

        # Only test the first country to avoid hammering every feed.
        test_country = _as_list(config["countries"])[0]
        url = self.FEED_URL_TEMPLATE.format(country=test_country)
        return await self._validate_http_access(session, url)

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for Meteoalarm.

        Returns:
            Voluptuous schema for Meteoalarm configuration.

        """
        country_options = dict(self.SUPPORTED_COUNTRIES)

        return common_config_schema(extra={
            vol.Required("countries", default=["united-kingdom"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    # HA's SelectSelectorConfig.options stub wants
                    # Sequence[SelectOptionDict]; a plain dict literal is
                    # accepted at runtime but mypy can't match it.
                    options=[{"label": v, "value": k} for k, v in country_options.items()],  # type: ignore[typeddict-item]
                    multiple=True,
                ),
            ),
        })
