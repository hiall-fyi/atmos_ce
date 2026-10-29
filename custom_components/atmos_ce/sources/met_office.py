"""Met Office weather warning source (UK).

Fetches alerts from the Met Office RSS feed.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, Final

import aiohttp
import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util.dt import async_get_time_zone, utcnow

from ..http_retry import require_shape
from ..models import Alert, get_color_for_level, get_icon_for_alert_type, resolve_severity
from ..source_base import (
    DEFAULT_FETCH_TIMEOUT,
    WeatherWarningSource,
    _as_list,
    async_parse_xml_checked,
    classify_by_keywords,
    common_config_schema,
    compute_alert_id,
    find_colour_word,
    raise_if_all_failed,
)

_LOGGER = logging.getLogger(__name__)

# the Met Office writes warning times as UK local clock time; assumed from one live warning (1e485c7c), UNVERIFIED
_UK_TIME_ZONE: Final = "Europe/London"

_MAX_WARNING_SPAN: Final = timedelta(days=31)

_MONTH_NUMBERS: Final[dict[str, int]] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


class MetOfficeSource(WeatherWarningSource):
    """Met Office weather warnings (UK).

    Supports yellow, amber, and red severity levels for rain, wind, snow,
    ice, fog, thunderstorms, heat, and cold.
    """

    RSS_URL = "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK"

    # UK Regions (as used by Met Office)
    UK_REGIONS: ClassVar[list[str]] = [
        "London & South East England",
        "South West England",
        "East Midlands",
        "West Midlands",
        "East of England",
        "North East England",
        "North West England",
        "Yorkshire & Humber",
        "Wales",
        "Scotland",
        "Northern Ireland",
    ]

    # UK Local Authorities (Unitary Authorities + Major Cities + Counties)
    UK_LOCAL_AUTHORITIES: ClassVar[list[str]] = [
        # England - Unitary Authorities (alphabetical)
        "Bath and North East Somerset", "Bedford", "Blackburn with Darwen", "Blackpool",
        "Bournemouth, Christchurch and Poole", "Bracknell Forest", "Brighton & Hove",
        "Bristol", "Buckinghamshire", "Central Bedfordshire", "Cheshire East",
        "Cheshire West and Chester", "Cornwall", "County Durham", "Cumberland",
        "Darlington", "Derby", "Dorset", "East Riding of Yorkshire", "Halton",
        "Hartlepool", "Herefordshire", "Isle of Wight", "Kingston upon Hull",
        "Leicester", "Luton", "Medway", "Middlesbrough", "Milton Keynes",
        "North East Lincolnshire", "North Lincolnshire", "North Northamptonshire",
        "North Somerset", "North Yorkshire", "Northumberland", "Nottingham",
        "Peterborough", "Plymouth", "Portsmouth", "Reading", "Redcar and Cleveland",
        "Rutland", "Shropshire", "Slough", "Somerset", "South Gloucestershire",
        "Southampton", "Southend-on-Sea", "Stockton-on-Tees", "Stoke-on-Trent",
        "Swindon", "Telford and Wrekin", "Thurrock", "Torbay", "Warrington",
        "West Berkshire", "West Northamptonshire", "Westmorland and Furness",
        "Wiltshire", "Windsor and Maidenhead", "Wokingham", "York",

        # England - Additional Major Cities (not already in unitary authorities)
        "London", "Birmingham", "Manchester", "Leeds", "Liverpool",
        "Newcastle", "Sheffield", "Oxford", "Cambridge", "Exeter",

        # England - Traditional Counties (for backward compatibility, not already listed)
        "Devon", "Hampshire", "West Sussex", "East Sussex", "Kent", "Surrey",
        "Berkshire", "Oxfordshire", "Hertfordshire", "Essex", "Suffolk", "Norfolk",
        "Cambridgeshire", "Northamptonshire", "Warwickshire", "Worcestershire",
        "Gloucestershire", "Staffordshire", "Derbyshire", "Nottinghamshire",
        "Lincolnshire", "Leicestershire", "Cheshire", "Lancashire", "Cumbria",
        "Tyne and Wear", "Durham", "South Yorkshire", "West Yorkshire",

        # Wales - Counties
        "Anglesey", "Gwynedd", "Conwy", "Denbighshire", "Flintshire",
        "Wrexham", "Powys", "Ceredigion", "Pembrokeshire",
        "Carmarthenshire", "Swansea", "Neath Port Talbot",
        "Bridgend", "Vale of Glamorgan", "Cardiff", "Rhondda Cynon Taf",
        "Merthyr Tydfil", "Caerphilly", "Blaenau Gwent", "Torfaen",
        "Monmouthshire", "Newport",

        # Scotland - Council Areas
        "Aberdeen", "Aberdeenshire", "Angus", "Argyll and Bute",
        "Clackmannanshire", "Dumfries and Galloway", "Dundee",
        "East Ayrshire", "East Dunbartonshire", "East Lothian",
        "East Renfrewshire", "Edinburgh", "Falkirk", "Fife",
        "Glasgow", "Highland", "Inverclyde", "Midlothian",
        "Moray", "North Ayrshire", "North Lanarkshire",
        "Orkney Islands", "Perth and Kinross", "Renfrewshire",
        "Scottish Borders", "Shetland Islands", "South Ayrshire",
        "South Lanarkshire", "Stirling", "West Dunbartonshire",
        "West Lothian", "Western Isles",

        # Northern Ireland - Counties
        "County Antrim", "County Armagh", "County Down",
        "County Fermanagh", "County Londonderry", "County Tyrone",
        "Belfast", "Derry", "Lisburn", "Newry",
    ]

    # Walked in order, first match wins. flood/flooding and
    # thunderstorm/thunder share a row each since they're the same type.
    _CLASSIFY_TABLE: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("flood", ("flood", "flooding")),
        ("coastal", ("coastal",)),
        ("rain", ("rain",)),
        ("wind", ("wind",)),
        ("snow", ("snow",)),
        ("ice", ("ice",)),
        ("fog", ("fog",)),
        ("thunderstorm", ("thunderstorm", "thunder")),
        ("heat", ("heat",)),
        ("cold", ("cold",)),
    )

    # the feed spells these two options differently from their label (checked against the Feb 2026 sample, not live)
    _LOCAL_AUTHORITY_ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "Bournemouth, Christchurch and Poole": ("Bournemouth Christchurch and Poole",),
        "County Durham": ("Durham",),
    }

    @property
    def source_id(self) -> str:
        """Return the unique identifier for this source."""
        return "met_office"

    @property
    def source_name(self) -> str:
        """Return the human-readable name for this source."""
        return "Met Office"

    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from the Met Office RSS feed."""
        _LOGGER.debug("Fetching alerts from Met Office RSS feed")

        try:
            xml_text = await self._fetch_checked(session, self.RSS_URL, timeout=DEFAULT_FETCH_TIMEOUT)

            _LOGGER.debug("Successfully fetched Met Office RSS feed")

            # Parse XML off the event loop with entity expansion disabled.
            data = await async_parse_xml_checked(xml_text, "Met Office RSS")

            rss: Any = data.get("rss")  # require_shape below proves it is a dict
            require_shape(isinstance(rss, dict), "Met Office", "no rss element")
            channel: Any = rss.get("channel")  # require_shape below proves it is a dict
            require_shape(isinstance(channel, dict), "Met Office", "no channel element")

            # xmltodict returns a dict for a single item, a list otherwise; no item is the legal quiet answer.
            items = _as_list(channel.get("item"))

            _LOGGER.debug("Found %d items in RSS feed", len(items))

            zone = await async_get_time_zone(_UK_TIME_ZONE)
            if zone is None:
                raise ValueError("Europe/London time zone data is missing")

            alerts = []
            for item in items:
                alert = self._parse_alert(item, zone)
                if alert:
                    alerts.append(alert)

            raise_if_all_failed(len(items), len(items) - len(alerts), "Met Office alerts")
            _LOGGER.debug("Parsed %d alerts from Met Office", len(alerts))

            # local_authorities match against locations; location_filters is
            # free-text, either a single string or a list.
            location_filters: list[str] = []
            local_authorities = config.get("local_authorities", [])
            if local_authorities:
                location_filters.extend(
                    term
                    for authority in local_authorities
                    for term in self._LOCAL_AUTHORITY_ALIASES.get(authority, (authority,))
                )

            custom_filters = config.get("location_filters", [])
            if isinstance(custom_filters, str):
                location_filters.append(custom_filters)
            elif custom_filters:
                location_filters.extend(custom_filters)

            filtered_alerts = alerts

            # Regions match against the alert summary/title, not a structured field.
            regions = config.get("regions", [])
            if regions:
                filtered_alerts = [
                    alert for alert in filtered_alerts
                    if any(region.lower() in alert.summary.lower() for region in regions)
                ]
                _LOGGER.debug(
                    "Filtered by regions %s: %d alerts remain",
                    regions,
                    len(filtered_alerts),
                )

            # Filter by local authorities + custom location filters
            # via base class method for consistency with other sources
            if location_filters:
                filtered_alerts = self._apply_location_filter(
                    filtered_alerts, {"location_filters": location_filters},
                )

            return filtered_alerts

        except aiohttp.ClientError as err:
            _LOGGER.exception(
                "HTTP error fetching Met Office alerts: %s (URL: %s)",
                err,
                self.RSS_URL,
            )
            raise

    def _parse_alert(self, item: dict, zone: tzinfo) -> Alert | None:
        """Parse a single Met Office alert from an RSS item."""
        try:
            title = item.get("title", "")
            description = item.get("description", "")
            link = item.get("link", "")
            pub_date = item.get("pubDate", "")

            if not title:
                _LOGGER.warning("Skipping alert with empty title")
                return None

            # Title format: "Yellow warning of rain affecting South West England"
            severity_name, level = resolve_severity(self._extract_severity(title))
            alert_type = self._extract_alert_type(title)
            locations = self._extract_locations(title, description)
            start_time, end_time = self._extract_times(description, pub_date, zone)

            alert = Alert(
                alert_id=f"met_office_{compute_alert_id('met_office', title + pub_date)}",
                source="met_office",
                alert_type=alert_type,
                severity=severity_name,
                level=level,
                start_time=start_time,
                end_time=end_time,
                locations=tuple(locations),
                summary=title,
                description=description,
                link=link,
                icon=get_icon_for_alert_type(alert_type),
                color=get_color_for_level(level),
            )

            _LOGGER.debug(
                "Parsed alert: %s (%s, level %d) for %s",
                alert_type,
                severity_name,
                level,
                ", ".join(locations[:2]) + ("..." if len(locations) > 2 else ""),
            )

            return alert

        except Exception as err:
            _LOGGER.exception(
                "Error parsing Met Office alert: %s. Item data: %s",
                err,
                str(item)[:500] if item else "(empty)",
            )
            return None

    def _extract_severity(self, title: str) -> str:
        """Extract the colour word from the title, or "" if it has none.

        "" (not "yellow") on no match: an unparseable title is unclassified,
        not a real moderate/yellow warning the feed never actually sent.
        The caller resolves "" to "unknown"/1 via resolve_severity.
        """
        return find_colour_word(title.split(" affecting ", 1)[0], ("red", "amber", "yellow")) or ""

    def _extract_alert_type(self, title: str) -> str:
        """Extract alert type from the warning part of the title."""
        # a place name after "affecting" can contain a type word (Leicestershire, Windsor, Snowdonia)
        return classify_by_keywords(title.split(" affecting ", 1)[0], self._CLASSIFY_TABLE)

    def _extract_locations(self, title: str, description: str = "") -> list[str]:
        """Extract locations from title and description.

        Real format: "Yellow warning of rain affecting South West England",
        with detailed locations in the description after the colon.
        """
        # First try to extract from description (more detailed)
        if description and ":" in description:
            # Format: "Yellow warning of rain affecting South West England:
            # Bournemouth Christchurch and Poole, Cornwall, Devon, Dorset..."
            parts = description.split(":", 1)
            if len(parts) == 2:
                location_part = parts[1].split(" valid from ")[0]  # strip the trailing validity period
                locations = [loc.strip() for loc in location_part.split(",")]
                locations = [loc for loc in locations if loc]

                if locations:
                    return locations

        # Fallback: extract region from title
        if " affecting " in title:
            region = title.split(" affecting ", 1)[1]
            return [region.strip()]

        # Old format fallback: "Yellow warning of rain for London"
        if " for " in title:
            location_part = title.split(" for ", 1)[1]
            locations = re.split(r"[,&]|\s+and\s+", location_part)
            locations = [loc.strip() for loc in locations if loc.strip()]
            return locations or ["UK"]

        return ["UK"]

    def _extract_times(self, description: str, pub_date: str, zone: tzinfo) -> tuple[str, str]:
        """Extract start and end times from description.

        Real format: "valid from 0500 Thu 05 Feb to 2100 Fri 06 Feb".
        """
        pattern = r"valid from (\d{4} \w+ \d{1,2} \w+) to (\d{4} \w+ \d{1,2} \w+)"
        match = re.search(pattern, description, re.IGNORECASE)

        if match:
            try:
                start_str = match.group(1)  # "0500 Thu 05 Feb"
                end_str = match.group(2)    # "2100 Fri 06 Feb"

                try:
                    reference = parsedate_to_datetime(pub_date)
                    if reference.tzinfo is None:
                        reference = reference.replace(tzinfo=UTC)
                except (TypeError, ValueError):
                    reference = utcnow()

                # a warning starts within about six months of the feed date, so the nearest year wins across New Year
                starts = [
                    parsed
                    for year in (reference.year - 1, reference.year, reference.year + 1)
                    if (parsed := self._parse_met_office_time(start_str, year, zone, latest=False))
                ]
                start = min(starts, key=lambda candidate: abs(candidate - reference), default=None)

                end = None
                if start is not None:
                    local_year = start.astimezone(zone).year
                    for year in (local_year, local_year + 1):
                        candidate = self._parse_met_office_time(end_str, year, zone, latest=True)
                        # a warning never lasts over a month, so an end far past the start is an inverted text
                        if candidate is not None and start <= candidate <= start + _MAX_WARNING_SPAN:
                            end = candidate
                            break

                if start is not None and end is not None:
                    return start.isoformat(), end.isoformat()

            except Exception as err:
                _LOGGER.debug("Failed to parse validity period: %s", err)

            _LOGGER.warning("Met Office validity period could not be read, using the feed date: %s", match.group(0))

        # Fallback: the feed occasionally uses phrasing the regex does
        # not cover (e.g. "valid from 12pm Friday to 6pm Saturday"). Use
        # pub_date as the start and leave end_time empty so downstream
        # consumers treat the alert as "until further notice" rather than
        # fabricating a fixed +24h window. A fabricated end would make
        # sensors like `time_until_end` lie to user automations.
        try:
            start_dt = parsedate_to_datetime(pub_date)
            return start_dt.isoformat(), ""
        except (TypeError, ValueError):
            # Final fallback: use current time as start, no end
            return utcnow().isoformat(), ""

    def _parse_met_office_time(
        self, time_str: str, year: int, zone: tzinfo, *, latest: bool,
    ) -> datetime | None:
        """Parse a "0500 Thu 05 Feb" UK local time string to an aware UTC datetime."""
        try:
            parts = time_str.split()
            if len(parts) < 4:
                return None

            time_part = parts[0]  # "0500"
            day = parts[2]        # "05"
            month = parts[3]      # "Feb"

            hour = int(time_part[:2])
            minute = int(time_part[2:])

            month_num = _MONTH_NUMBERS.get(month[:3].title())
            if month_num is None:
                return None

            # changeover night: earliest instant for a start, latest for an end, so a warning is never late or hidden
            instants = {
                datetime(year, month_num, int(day), hour, minute, tzinfo=zone, fold=fold).astimezone(UTC)
                for fold in (0, 1)
            }
            return max(instants) if latest else min(instants)

        except Exception as err:
            _LOGGER.debug("Failed to parse Met Office time '%s': %s", time_str, err)
            return None

    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate configuration by testing API access."""
        return await self._validate_http_access(session, self.RSS_URL)

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for this source."""
        return common_config_schema(extra={
            vol.Optional("regions", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=self.UK_REGIONS,
                    multiple=True,
                ),
            ),
            vol.Optional("local_authorities", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=self.UK_LOCAL_AUTHORITIES,
                    multiple=True,
                ),
            ),
        })
