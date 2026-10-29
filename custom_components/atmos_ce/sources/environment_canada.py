"""Environment Canada weather warnings source (Canada).

This module implements the Environment Canada weather warning source plugin,
which fetches alerts from the Environment Canada CAP XML feeds hosted on
the Meteorological Service of Canada Datamart.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, ClassVar, NamedTuple
from xml.parsers.expat import ExpatError

import aiohttp
import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util.dt import utcnow

from ..http_retry import UpstreamResponseError, UpstreamStatusError, require_shape
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
    raise_if_all_failed,
    values_or_raise,
)

_LOGGER = logging.getLogger(__name__)

_ANCHOR = re.compile(r"""<a\s[^>]*?href\s*=\s*["']?([^"'\s>]+)[^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)


def _has_entry_anchor(listing_html: str) -> bool:
    """Return True when a listing has an anchor other than the sort links and Parent Directory."""
    return any(
        not href.startswith("?") and "parent directory" not in text.lower()
        for href, text in _ANCHOR.findall(listing_html)
    )


class _CapResult(NamedTuple):
    """One parsed CAP file: its id, the ids it supersedes, its alert if kept, and whether it was unparseable."""

    identifier: str
    superseded: frozenset[str]
    alert: Alert | None
    malformed: bool = False


class EnvironmentCanadaSource(WeatherWarningSource):
    """Environment Canada weather warnings (Canada via CAP XML feeds).

    This source fetches weather warnings from the Environment Canada
    Datamart CAP XML feeds. It walks the date, office and hour folders
    of yesterday and today, then fetches individual CAP files concurrently
    with a semaphore to avoid overwhelming the server.
    """

    BASE_URL = "https://dd.weather.gc.ca/today/alerts/cap"
    ARCHIVE_URL: ClassVar[str] = "https://dd.weather.gc.ca/{day}/WXO-DD/alerts/cap/{day}/"
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

    # SGC province prefix; all seen in the live archive except PE, the standard value (unverified live).
    _SGC_PROVINCE_CODE: ClassVar[dict[str, str]] = {
        "AB": "48",
        "BC": "59",
        "MB": "46",
        "NB": "13",
        "NL": "10",
        "NS": "12",
        "NT": "61",
        "NU": "62",
        "ON": "35",
        "PE": "11",
        "QC": "24",
        "SK": "47",
        "YT": "60",
    }

    @property
    def source_id(self) -> str:
        """Return unique identifier for this source."""
        return "environment_canada"

    @property
    def source_name(self) -> str:
        """Return human-readable name."""
        return "Environment Canada"

    @classmethod
    def _day_urls(cls, now: datetime) -> list[str]:
        """Return today's alias folder and yesterday's archive folder (UTC days)."""
        return [
            f"{cls.BASE_URL}/{now:%Y%m%d}/",
            cls.ARCHIVE_URL.format(day=f"{now - timedelta(days=1):%Y%m%d}"),
        ]

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from yesterday's and today's CAP folders, since an alert lives up to a day."""
        provinces = _as_list(config.get("provinces", ["ON"]))

        day_urls = self._day_urls(utcnow())

        semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_REQUESTS)

        async def _list_links(
            url: str,
            pattern: str,
            suffix: str = "",
            *,
            missing_ok: bool = False,
            allow_empty: bool = False,
        ) -> list[str]:
            """Return ``url`` + each link matching ``pattern`` (+ ``suffix``) in one directory listing."""
            async with semaphore:
                try:
                    listing_html = await self._fetch_checked(session, url, timeout=DEFAULT_FETCH_TIMEOUT)
                except UpstreamStatusError as err:
                    if err.status == 404 and missing_ok:
                        _LOGGER.debug("Environment Canada folder %s not found, no alerts there", url)
                        return []
                    raise
            require_shape(
                "Index of" in listing_html, "Environment Canada listing", f"{url} is not a directory listing",
            )
            links = re.findall(pattern, listing_html)
            if not links and not allow_empty:
                msg = f"Environment Canada listing {url} has no entries"
                raise UpstreamResponseError(msg)
            if not links and _has_entry_anchor(listing_html):
                msg = f"Environment Canada listing {url} has entries this reader does not recognise"
                raise UpstreamResponseError(msg)
            return [f"{url}{link}{suffix}" for link in links]

        async def _cap_urls_for_day(day_url: str) -> list[str]:
            """Return the CAP file URLs of one date folder (empty when the folder does not exist yet)."""
            office_urls = await _list_links(
                day_url, r'href="([A-Z]{4})/"', "/", missing_ok=True, allow_empty=True,
            )
            _LOGGER.debug("Found %d office folders under %s", len(office_urls), day_url)
            office_results = await asyncio.gather(
                *(_list_links(office_url, r'href="(\d{2})/"', "/") for office_url in office_urls),
                return_exceptions=True,
            )
            hour_urls = [
                url
                for urls in values_or_raise(
                    office_results, "Environment Canada office listing", allow_partial=False,
                )
                for url in urls
            ]
            hour_results = await asyncio.gather(
                *(_list_links(hour_url, r'href="([^"]+\.cap)"') for hour_url in hour_urls),
                return_exceptions=True,
            )
            return [
                url
                for urls in values_or_raise(
                    hour_results, "Environment Canada hour listing", allow_partial=False,
                )
                for url in urls
            ]

        day_results = await asyncio.gather(
            *(_cap_urls_for_day(day_url) for day_url in day_urls), return_exceptions=True,
        )
        cap_urls = [
            url
            for urls in values_or_raise(
                day_results, "Environment Canada day listing", allow_partial=False,
            )
            for url in urls
        ]

        _LOGGER.debug("Total CAP URLs to fetch: %d", len(cap_urls))

        if not cap_urls:
            return []

        # Phase 3: Fetch and parse all CAP files concurrently
        async def _fetch_cap(url: str) -> _CapResult:
            """Fetch and parse a single CAP XML file."""
            async with semaphore:
                xml_text = await self._fetch_checked(session, url, timeout=DEFAULT_FETCH_TIMEOUT)
                try:
                    # Offload XML parse so many concurrent CAP files don't
                    # serialize on the event loop.
                    data = await async_parse_xml(xml_text)
                except ExpatError as err:
                    # A bad 200 file stays in the folder all day, so one must not fail every poll.
                    _LOGGER.warning("Skipped malformed CAP file %s: %s", url, err)
                    return _CapResult("", frozenset(), None, malformed=True)
                if not isinstance(data.get("alert"), dict):
                    _LOGGER.warning("Skipped CAP file %s: XML document without an alert element", url)
                    return _CapResult("", frozenset(), None, malformed=True)
                identifier = self._cap_identifier(data)
                references = self._cap_references(data)
                try:
                    alert = self._parse_alert(data, provinces, raise_errors=True)
                except Exception as err:  # broad: one unusable file is skipped and counted, logged here
                    _LOGGER.warning("Skipped unparseable CAP file %s: %s", url, err)
                    return _CapResult(identifier, references, None, malformed=True)
                return _CapResult(identifier, references, alert)

        cap_results = await asyncio.gather(
            *(_fetch_cap(url) for url in cap_urls),
            return_exceptions=True,
        )
        results: list[_CapResult] = values_or_raise(
            cap_results, "Environment Canada CAP fetch", allow_partial=False,
        )
        raise_if_all_failed(len(results), sum(r.malformed for r in results), "Environment Canada CAP parse")

        # References come from every message, so an ended message removes its target.
        superseded = set().union(*(r.superseded for r in results))
        all_alerts = [
            r.alert for r in results
            if r.alert is not None and r.identifier not in superseded
        ]

        _LOGGER.debug("Fetched %d total alerts from Environment Canada", len(all_alerts))
        return self._apply_location_filter(all_alerts, config)

    @staticmethod
    def _cap_identifier(data: dict) -> str:
        """Return the CAP identifier of a parsed message, or an empty string."""
        alert_data = data.get("alert") if isinstance(data, dict) else None
        if not isinstance(alert_data, dict):
            return ""
        return str(alert_data.get("identifier") or "")

    @staticmethod
    def _cap_references(data: dict) -> frozenset[str]:
        """Return the identifiers a message references (``sender,identifier,sent`` tokens)."""
        alert_data = data.get("alert") if isinstance(data, dict) else None
        if not isinstance(alert_data, dict):
            return frozenset()
        parts = (token.split(",") for token in str(alert_data.get("references") or "").split())
        return frozenset(p[1] for p in parts if len(p) > 1)

    def _parse_alert(self, data: dict, provinces: list[str], *, raise_errors: bool = False) -> Alert | None:
        """Parse a single Environment Canada CAP alert."""
        try:
            alert_data = data.get("alert", {})
            info = alert_data.get("info", {})

            # Bilingual alerts carry multiple info blocks; prefer the English one.
            if isinstance(info, list):
                for i in info:
                    if i.get("language", "").startswith("en"):
                        info = i
                        break
                else:
                    info = info[0]

            alert_id = alert_data.get("identifier", "")
            sent = alert_data.get("sent", "")
            event = info.get("event", "Unknown")
            severity = info.get("severity", "Minor")
            headline = info.get("headline", "")
            description = info.get("description", "")
            instruction = info.get("instruction", "")
            effective = info.get("effective", sent)
            onset = info.get("onset", effective)
            expires = info.get("expires", "")
            web = info.get("web", "https://weather.gc.ca/")

            if alert_data.get("msgType") == "Cancel" or info.get("responseType") == "AllClear":
                return None

            areas = [a for a in _as_list(info.get("area")) if isinstance(a, dict)]

            if provinces:
                wanted = {
                    self._SGC_PROVINCE_CODE[p] for p in provinces if p in self._SGC_PROVINCE_CODE
                }
                province_match = any(
                    str(geocode.get("value", ""))[:2] in wanted
                    for area in areas
                    for geocode in _as_list(area.get("geocode"))
                    if isinstance(geocode, dict)
                    and str(geocode.get("valueName", "")).startswith("profile:CAP-CP:Location")
                )
                if not province_match:
                    _LOGGER.debug(
                        "Skipping Environment Canada alert %s: no area in provinces %s",
                        alert_id, provinces,
                    )
                    return None

            alert_name_param = None
            parameters = _as_list(info.get("parameter", []))
            for param in parameters:
                value_name = param.get("valueName", "")
                if "Alert_Name" in value_name:
                    alert_name_param = param.get("value", "")

            alert_type = self._classify_event(event)
            severity_name, level = self._map_severity(severity, alert_name_param)
            locations = tuple(a["areaDesc"] for a in areas if a.get("areaDesc")) or ("Unknown",)

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
                # Empty = "until further notice" (see helpers.get_active_alerts).
                # Falling back to onset made end_time == start_time, a
                # zero-length window that could never register as active.
                end_time=expires,
                locations=locations,
                summary=headline,
                description=full_description,
                link=web,
                icon=get_icon_for_alert_type(alert_type),
                color=get_color_for_level(level),
            )

        except Exception as err:  # one malformed CAP message must not drop the rest of the poll
            if raise_errors:
                raise
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
        """Classify an Environment Canada event string into a normalised alert type."""
        return classify_by_keywords(event, cls._CLASSIFY_TABLE)

    @staticmethod
    def _map_severity(severity: str, alert_name: str | None) -> tuple[str, int]:
        """Return the colour word in ``alert_name`` (EN or FR) if any, else the CAP severity."""
        if alert_name:
            alert_name_lower = alert_name.lower()
            if "red" in alert_name_lower or "rouge" in alert_name_lower:
                return "red", 4
            if "orange" in alert_name_lower:
                return "orange", 3
            if "yellow" in alert_name_lower or "jaune" in alert_name_lower:
                return "yellow", 2

        return resolve_severity(severity)

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing feed access."""
        valid, error = self._validate_list_selection(
            config, "provinces", self.SUPPORTED_PROVINCES,
            singular="province", plural="provinces",
        )
        if not valid:
            return False, error

        # Today's folder appears with the day's first file; yesterday's covers the hours before.
        for url in self._day_urls(utcnow()):
            valid, error = await self._validate_http_access(session, url)
            if valid:
                return True, None
        return False, error

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for Environment Canada."""
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
