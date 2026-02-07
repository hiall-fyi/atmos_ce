"""Met Office weather warning source (UK).

This module implements the Met Office weather warning source plugin,
which fetches alerts from the Met Office RSS feed.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar

import aiohttp
import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util.dt import utcnow

from ..models import Alert, get_color_for_level, get_icon_for_alert_type
from ..source_base import (
    DEFAULT_FETCH_TIMEOUT,
    SEVERITY_MAP,
    WeatherWarningSource,
    _as_list,
    async_parse_xml,
    common_config_schema,
    compute_alert_id,
)

_LOGGER = logging.getLogger(__name__)


class MetOfficeSource(WeatherWarningSource):
    """Met Office weather warnings (UK).

    This source fetches weather warnings from the Met Office RSS feed.
    It supports yellow, amber, and red severity levels for various
    weather types including rain, wind, snow, ice, fog, thunderstorms,
    heat, and cold.

    Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
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

    # Alert type mapping, specific types first, then standard
    ALERT_TYPE_MAP: ClassVar[dict[str, str]] = {
        "flood": "flood",
        "flooding": "flood",
        "coastal": "coastal",
        "rain": "rain",
        "wind": "wind",
        "snow": "snow",
        "ice": "ice",
        "fog": "fog",
        "thunderstorm": "thunderstorm",
        "thunder": "thunderstorm",
        "heat": "heat",
        "cold": "cold",
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
        """Fetch alerts from Met Office RSS feed.

        Args:
            session: aiohttp client session
            config: Source configuration

        Returns:
            List of Alert objects

        Raises:
            aiohttp.ClientError: If HTTP request fails

        Requirements: 14.1, 14.3, 14.4, 14.5

        """
        _LOGGER.debug("Fetching alerts from Met Office RSS feed")

        try:
            response = await self._fetch_with_retry(
                session, self.RSS_URL, timeout=DEFAULT_FETCH_TIMEOUT,
            )
            async with response:
                if response.status != 200:
                    _LOGGER.warning(
                        "Met Office RSS returned HTTP %s, endpoint may be deprecated",
                        response.status,
                    )
                    return []
                xml_text = await response.text()

            _LOGGER.debug("Successfully fetched Met Office RSS feed")

            # Parse XML off the event loop with entity expansion disabled.
            try:
                data = await async_parse_xml(xml_text)
            except Exception as parse_err:
                _LOGGER.error(
                    "Failed to parse Met Office XML: %s. XML snippet: %s",
                    parse_err,
                    xml_text[:500] if xml_text else "(empty)",
                )
                raise

            # Handle empty or invalid XML
            if data is None or not isinstance(data, dict):
                _LOGGER.warning("Empty or invalid XML from Met Office")
                return []

            # Get items, handling None values
            rss = data.get("rss", {})
            if not isinstance(rss, dict):
                _LOGGER.warning("Invalid RSS structure from Met Office")
                return []

            channel = rss.get("channel", {})
            if channel is None or not isinstance(channel, dict):
                _LOGGER.debug("Empty channel in RSS feed")
                return []

            items = channel.get("item", [])

            # xmltodict returns a dict for a single item, a list otherwise.
            items = _as_list(items)

            _LOGGER.debug("Found %d items in RSS feed", len(items))

            # Parse each item into an Alert
            alerts = []
            for item in items:
                alert = self._parse_alert(item)
                if alert:
                    alerts.append(alert)

            _LOGGER.debug("Parsed %d alerts from Met Office", len(alerts))

            # Build location filters
            location_filters: list[str] = []

            # Add local authority filters (match against locations list)
            local_authorities = config.get("local_authorities", [])
            if local_authorities:
                location_filters.extend(local_authorities)

            # Add custom location filters
            custom_filters = config.get("location_filters", [])
            if isinstance(custom_filters, str):
                location_filters.append(custom_filters)
            elif custom_filters:
                location_filters.extend(custom_filters)

            # Apply filtering
            filtered_alerts = alerts

            # Filter by regions (match against summary/title)
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

    def _parse_alert(self, item: dict) -> Alert | None:
        """Parse a single Met Office alert from RSS item.

        Args:
            item: RSS item dictionary from xmltodict

        Returns:
            Alert object or None if parsing fails

        Requirements: 14.3, 14.4, 14.5, 14.6

        """
        try:
            title = item.get("title", "")
            description = item.get("description", "")
            link = item.get("link", "")
            pub_date = item.get("pubDate", "")

            if not title:
                _LOGGER.warning("Skipping alert with empty title")
                return None

            # Extract severity and alert type from title
            # Format: "Yellow warning of rain affecting South West England"
            severity = self._extract_severity(title)
            alert_type = self._extract_alert_type(title)

            # Extract locations from description (more detailed than title)
            locations = self._extract_locations(title, description)

            # Parse times from description
            start_time, end_time = self._extract_times(description, pub_date)

            # Get severity level
            # Met Office yellow/amber/red align to the shared CAP table:
            # yellow=2 (advisory), amber=3 (warning), red=4 (extreme).
            level = SEVERITY_MAP.get(severity, 1)

            # Create alert
            alert = Alert(
                alert_id=f"met_office_{compute_alert_id('met_office', title + pub_date)}",
                source="met_office",
                alert_type=alert_type,
                severity=severity,
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
                severity,
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
        """Extract severity from title.

        Args:
            title: Alert title

        Returns:
            Severity string (yellow, amber, red)

        Requirements: 14.3, 14.6

        """
        title_lower = title.lower()

        # Check in order of severity (highest first)
        for severity in ["red", "amber", "yellow"]:
            if severity in title_lower:
                return severity

        # Default to yellow if not found
        return "yellow"

    def _extract_alert_type(self, title: str) -> str:
        """Extract alert type from title.

        Args:
            title: Alert title

        Returns:
            Alert type string

        Requirements: 14.4

        """
        title_lower = title.lower()

        # Check for each alert type
        for keyword, alert_type in self.ALERT_TYPE_MAP.items():
            if keyword in title_lower:
                return alert_type

        # Default to unknown
        return "unknown"

    def _extract_locations(self, title: str, description: str = "") -> list[str]:
        """Extract locations from title and description.

        Args:
            title: Alert title
            description: Alert description (contains detailed locations)

        Returns:
            List of location strings

        Requirements: 14.5

        """
        # Real format: "Yellow warning of rain affecting South West England"
        # Detailed locations are in description after the colon

        # First try to extract from description (more detailed)
        if description and ":" in description:
            # Format: "Yellow warning of rain affecting South West England:
            # Bournemouth Christchurch and Poole, Cornwall, Devon, Dorset..."
            parts = description.split(":", 1)
            if len(parts) == 2:
                location_part = parts[1].split(" valid from ")[0]  # Remove time part

                # Split by commas
                locations = [loc.strip() for loc in location_part.split(",")]
                locations = [loc for loc in locations if loc]

                if locations:
                    return locations

        # Fallback: extract region from title
        # Format: "Yellow warning of rain affecting South West England"
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

    def _extract_times(self, description: str, pub_date: str) -> tuple[str, str]:
        """Extract start and end times from description.

        Args:
            description: Alert description
            pub_date: Publication date string

        Returns:
            Tuple of (start_time, end_time) in ISO 8601 format

        Requirements: 14.5

        """
        # Real format: "valid from 0500 Thu 05 Feb to 2100 Fri 06 Feb"
        pattern = r"valid from (\d{4} \w+ \d{1,2} \w+) to (\d{4} \w+ \d{1,2} \w+)"
        match = re.search(pattern, description, re.IGNORECASE)

        if match:
            try:
                start_str = match.group(1)  # "0500 Thu 05 Feb"
                end_str = match.group(2)    # "2100 Fri 06 Feb"

                # Parse the time strings
                # Format: "0500 Thu 05 Feb" -> need to add year

                # Get current year from pub_date
                try:
                    pub_dt = parsedate_to_datetime(pub_date)
                    year = pub_dt.year
                except Exception:
                    year = utcnow().year

                # Parse start time
                # "0500 Thu 05 Feb" -> "Thu, 05 Feb 2026 05:00:00 GMT"
                start_time_str = self._parse_met_office_time(start_str, year)
                end_time_str = self._parse_met_office_time(end_str, year)

                if start_time_str and end_time_str:
                    return start_time_str, end_time_str

            except Exception as err:
                _LOGGER.debug("Failed to parse validity period: %s", err)

        # Fallback: the feed occasionally uses phrasing the regex does
        # not cover (e.g. "valid from 12pm Friday to 6pm Saturday"). Use
        # pub_date as the start and leave end_time empty so downstream
        # consumers treat the alert as "until further notice" rather than
        # fabricating a fixed +24h window. A fabricated end would make
        # sensors like `time_until_end` lie to user automations.
        try:
            start_dt = parsedate_to_datetime(pub_date)
            return start_dt.isoformat(), ""
        except Exception:
            # Final fallback: use current time as start, no end
            return utcnow().isoformat(), ""

    def _parse_met_office_time(self, time_str: str, year: int) -> str | None:
        """Parse Met Office time format to ISO 8601.

        Args:
            time_str: Time string like "0500 Thu 05 Feb"
            year: Year to use

        Returns:
            ISO 8601 datetime string or None if parsing fails

        """
        try:
            # "0500 Thu 05 Feb" -> extract components
            parts = time_str.split()
            if len(parts) < 4:
                return None

            time_part = parts[0]  # "0500"
            day = parts[2]        # "05"
            month = parts[3]      # "Feb"

            # Parse time
            hour = int(time_part[:2])
            minute = int(time_part[2:])

            # Parse month
            month_map = {
                "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
                "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
                "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
            }
            month_num = month_map.get(month, 1)

            # Create datetime
            dt = datetime(year, month_num, int(day), hour, minute, tzinfo=UTC)
            return dt.isoformat()

        except Exception as err:
            _LOGGER.debug("Failed to parse Met Office time '%s': %s", time_str, err)
            return None

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
        return await self._validate_http_access(session, self.RSS_URL)

    def get_config_schema(self) -> vol.Schema:
        """Return configuration schema for this source.

        Returns:
            Voluptuous schema for configuration

        Requirements: 11.3, 12.1

        """
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
