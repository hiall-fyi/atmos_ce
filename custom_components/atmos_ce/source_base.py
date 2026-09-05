"""Abstract base class for weather warning sources."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Any

import aiohttp
import voluptuous as vol
import xmltodict
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import (
    DEFAULT_UPDATE_INTERVAL_MIN,
    MAX_UPDATE_INTERVAL_MIN,
    MIN_UPDATE_INTERVAL_MIN,
)
from .const import SEVERITY_MAP as SEVERITY_MAP  # noqa: PLC0414 (re-export for source plugins)
from .helpers import filter_by_location
from .http_retry import DEFAULT_FETCH_TIMEOUT, async_fetch_with_retry
from .models import Alert

_LOGGER = logging.getLogger(__name__)


# Sources map upstream wording to a level via SEVERITY_MAP, and name it via
# models.get_severity_for_level.


def compute_alert_id(source_id: str, upstream_id: str) -> str:
    """Compute a canonical 16-hex-char alert ID.

    Format: ``sha256(f"{source_id}|{upstream_id}")[:16]``. The pipe
    separator prevents cross-source collisions when two feeds happen
    to emit the same upstream identifier. 16 hex chars = 64 bits, so
    collision probability at the scale of a few thousand active
    alerts is negligible.

    Args:
        source_id: The ``source_id`` property of the source plugin
            (e.g. ``"nws"``, ``"met_office"``, ``"dwd"``).
        upstream_id: Whatever the source considers canonical, CAP
            ``<identifier>``, NWS ``properties.id``, DWD ``IDENTIFIER``,
            Atom ``<id>``, a composite string for CWA, etc.

    Returns:
        A 16-character lowercase hex string. Callers typically prefix
        with ``f"{source_id}_"`` for log legibility.

    """
    return hashlib.sha256(
        f"{source_id}|{upstream_id}".encode(),
    ).hexdigest()[:16]


def classify_by_keywords(
    text: str,
    table: tuple[tuple[str, tuple[str, ...]], ...],
    default: str = "unknown",
) -> str:
    """Return the first alert type whose keyword set matches *text*.

    The *table* is walked in order and the first matching row wins, so
    callers list more specific types before generic ones.

    Matching is case-insensitive (``text`` is lowercased once). Keyword
    entries must therefore be lowercase; non-Latin keywords (e.g. the CWA
    Chinese phenomena strings) are unaffected by lowercasing and match
    verbatim.

    Args:
        text: The source event / group string to classify.
        table: Ordered ``(alert_type, (keyword, ...))`` rows.
        default: Returned when no row matches (defaults to ``"unknown"``).

    Returns:
        The matched alert type, or *default*.

    """
    lowered = text.lower()
    for alert_type, keywords in table:
        if any(keyword in lowered for keyword in keywords):
            return alert_type
    return default


def _as_list(value: Any) -> list[Any]:  # noqa: ANN401 (accepts xmltodict's dict|list|str|None)
    """Coerce a value to a list, following the xmltodict/Atom convention.

    xmltodict and several feed parsers return a single dict when exactly
    one child is present and a list otherwise. This helper normalises
    both shapes:

    - ``None`` or any falsy value -> ``[]`` (matches the existing
      ``[items] if items else []`` idiom used across source parsers).
    - An existing list -> returned unchanged (identity preserved).
    - Any other truthy value -> wrapped in a single-element list.

    Args:
        value: The possibly-list, possibly-scalar value.

    Returns:
        A list. Empty for falsy inputs, otherwise containing the
        original items.

    """
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


async def async_parse_xml(xml_input: str | bytes) -> dict[str, Any]:
    """Parse XML off the event loop with entity expansion disabled.

    ``xmltodict.parse`` walks the full DOM synchronously; on HA this
    blocks the event loop while it runs. Environment Canada fans out
    hundreds of CAP files per update, each ~20 KB, which adds up to
    hundreds of milliseconds of blocked time. Offloading to an executor
    thread keeps the loop responsive.

    ``disable_entities=True`` is the xmltodict default in 0.13+, but we
    pass it explicitly as defence-in-depth against future API drift or
    a dependency downgrade, the feeds we parse are trusted today but
    could be mirrored/proxied and billion-laughs DoS is cheap to block.

    Args:
        xml_input: Raw XML as a string or bytes.

    Returns:
        The parsed document as a nested dict.

    Raises:
        Whatever xmltodict / expat raise on malformed input, callers
        should catch and log as they already do.

    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: xmltodict.parse(xml_input, disable_entities=True),
    )


def common_config_schema(
    extra: dict[vol.Marker, object] | None = None,
) -> vol.Schema:
    """Build a config schema with the shared fields every source uses.

    Shared fields: ``enabled``, ``update_interval``, ``location_filters``.
    Source-specific fields are passed via *extra*.

    Args:
        extra: Additional schema entries to merge.

    Returns:
        Voluptuous schema.

    """
    base: dict[vol.Marker, object] = {
        vol.Optional("enabled", default=True): cv.boolean,
        vol.Optional(
            "update_interval", default=DEFAULT_UPDATE_INTERVAL_MIN,
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_UPDATE_INTERVAL_MIN, max=MAX_UPDATE_INTERVAL_MIN),
        ),
        # default="" keeps the field clearable: the options flow merges over
        # the existing config, so a key absent from an empty submit would
        # keep its old value.
        vol.Optional("location_filters", default=""): selector.TextSelector(
            selector.TextSelectorConfig(multiline=False),
        ),
    }
    if extra:
        base.update(extra)
    return vol.Schema(base)


class WeatherWarningSource(ABC):
    """Abstract base class for weather warning sources.

    All weather warning source plugins must inherit from this class
    and implement all required methods. This ensures a consistent
    interface across all sources.
    """

    @property
    def has_warning_backend(self) -> bool:
        """Whether this source can fetch weather warnings.

        Override in subclasses that have no warning backend
        (e.g. WorldwideForecastSource).

        Returns:
            True if the source has a warning backend.

        """
        return True

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Return unique identifier for this source.

        This should be a lowercase string with underscores, e.g., 'met_office'.

        Returns:
            Source identifier

        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return human-readable name for this source.

        This will be displayed in the UI, e.g., 'Met Office'.

        Returns:
            Source display name

        """
        ...

    @abstractmethod
    async def fetch_alerts(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> list[Alert]:
        """Fetch alerts from the source API.

        This method should:
        1. Make async HTTP request(s) to the source API
        2. Parse the response (XML, JSON, etc.)
        3. Convert to Alert objects
        4. Apply location filtering if configured
        5. Return list of alerts

        Args:
            session: aiohttp ClientSession for making requests
            config: Source-specific configuration dictionary

        Returns:
            List of Alert objects

        Raises:
            aiohttp.ClientError: If API request fails
            ValueError: If response parsing fails

        """
        ...

    @abstractmethod
    async def validate_config(
        self,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate source configuration.

        This method should:
        1. Check required fields are present
        2. Test API access (make a test request)
        3. Validate API key if required
        4. Return success status and error message

        Args:
            session: aiohttp ClientSession for making requests
            config: Source-specific configuration dictionary

        Returns:
            Tuple of (success: bool, error_message: str | None)

        """
        ...

    @abstractmethod
    def get_config_schema(self) -> vol.Schema:
        """Return voluptuous schema for config flow.

        This schema defines the configuration fields that will be
        displayed in the Home Assistant config flow UI.

        Returns:
            Voluptuous schema dictionary

        """
        ...

    async def _fetch_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout = DEFAULT_FETCH_TIMEOUT,
    ) -> aiohttp.ClientResponse:
        """Perform an HTTP GET with retry on transient errors.

        Delegates to the shared ``async_fetch_with_retry`` function.

        Args:
            session: aiohttp client session.
            url: Request URL.
            params: Optional query parameters.
            headers: Optional request headers.
            timeout: Request timeout (per attempt).

        Returns:
            The successful ``aiohttp.ClientResponse``.

        Raises:
            aiohttp.ClientResponseError: After all retries exhausted.
            aiohttp.ClientError: On non-retryable client errors.
            TimeoutError: After all retries exhausted on timeout.

        """
        return await async_fetch_with_retry(
            session,
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            source_label=self.source_name,
            logger=_LOGGER,
        )

    def _apply_location_filter(
        self, alerts: list[Alert], config: dict[str, Any],
    ) -> list[Alert]:
        """Apply location_filters from *config* to a list of alerts.

        Args:
            alerts: Unfiltered alert list.
            config: Source configuration dictionary.

        Returns:
            Filtered alert list, or the original list if no filters configured.

        """
        location_filters = config.get("location_filters", [])
        if location_filters:
            return filter_by_location(alerts, location_filters)
        return alerts

    async def _fetch_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout = DEFAULT_FETCH_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Fetch a URL and decode the JSON body, or None on a non-200 status.

        Wraps the ``_fetch_with_retry`` → status-check → ``response.json()``
        boilerplate that single-request JSON sources repeat. Returns None
        (after logging a warning) when the server answers non-200 so the
        caller can treat it as "no alerts this cycle". Transient 403/429/5xx
        and auth failures are handled inside ``_fetch_with_retry``.

        Args:
            session: aiohttp client session.
            url: Request URL.
            params: Optional query parameters.
            headers: Optional request headers.
            timeout: Request timeout (per attempt).

        Returns:
            The decoded JSON dict, or None on a non-200 response.

        """
        response = await self._fetch_with_retry(
            session, url, params=params, headers=headers, timeout=timeout,
        )
        async with response:
            if response.status != 200:
                _LOGGER.warning(
                    "%s returned HTTP %s", self.source_name, response.status,
                )
                return None
            return await response.json()

    @staticmethod
    def _validate_list_selection(
        config: dict[str, Any],
        key: str,
        supported: dict[str, str],
        *,
        singular: str,
        plural: str,
    ) -> tuple[bool, str | None]:
        """Validate a multi-select config field against a supported set.

        Shared by the list-based sources (Meteoalarm countries,
        Environment Canada provinces): checks at least one item is
        selected and that every selected item is in *supported*.

        Args:
            config: Source configuration dictionary.
            key: Config key holding the selected list (e.g. ``"countries"``).
            supported: Mapping of valid identifiers to display names.
            singular: Singular noun for the "at least one" message.
            plural: Plural noun for the "unsupported" message.

        Returns:
            ``(True, None)`` when valid, otherwise ``(False, message)``.

        """
        selected = _as_list(config.get(key, []))
        if not selected:
            return False, f"At least one {singular} must be selected"

        invalid = [item for item in selected if item not in supported]
        if invalid:
            supported_str = ", ".join(supported.keys())
            unsupported_str = ", ".join(invalid)
            return (
                False,
                (
                    f"Unsupported {plural}: {unsupported_str}. "
                    f"Must be one of: {supported_str}"
                ),
            )
        return True, None

    async def _validate_http_access(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """Validate API access with a test request, retrying transient errors.

        A non-200 that survives retries (e.g. a 404 on a moved endpoint)
        fails validation, so a source that would never return data can't
        be added.

        Returns:
            Tuple of (success, error_message).

        """
        try:
            response = await self._fetch_with_retry(
                session,
                url,
                params=params,
                headers=headers,
                # Per attempt: all retries must fit inside HTTP_TIMEOUT.
                timeout=aiohttp.ClientTimeout(total=10),
            )
            async with response:
                if response.status != 200:
                    return (
                        False,
                        f"{self.source_name} returned HTTP {response.status}",
                    )
            _LOGGER.debug("%s configuration validated successfully", self.source_name)
            return True, None

        except aiohttp.ClientError as err:
            error_msg = f"Failed to connect to {self.source_name}: {err}"
            _LOGGER.exception(error_msg)
            return False, error_msg
        except Exception as err:
            error_msg = (
                f"Unexpected error validating {self.source_name} config: {err}"
            )
            _LOGGER.exception(error_msg)
            return False, error_msg
