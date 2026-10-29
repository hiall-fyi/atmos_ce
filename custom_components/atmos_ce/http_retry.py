"""Shared HTTP GET retry logic for Atmos CE.

Provides ``async_fetch_with_retry``, a single implementation of
exponential-backoff-with-jitter used by both ``WeatherWarningSource``
(alert fetching) and ``OpenMeteoBackend`` (forecast / AQ fetching).
"""
from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import random
import re
from datetime import UTC, datetime
from typing import Any, Final, Literal, overload

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from multidict import CIMultiDict, CIMultiDictProxy

from .const import (
    DEFAULT_USER_AGENT,
    MAX_RETRY_ATTEMPTS,
    MAX_RETRY_DELAY,
    RETRY_BASE_DELAY,
)

_LOGGER = logging.getLogger(__name__)

# Default timeout for HTTP requests. Split into connect/read components so
# a slow-to-first-byte server can't blow the total budget; `total` is still
# set generously enough to swallow large payloads (DWD GeoJSON, EC CAP
# bundles) on slow links.
DEFAULT_FETCH_TIMEOUT: Final = aiohttp.ClientTimeout(
    total=60, sock_connect=10, sock_read=30,
)

# Retry-After clamping bounds.
_RETRY_AFTER_MIN_S: Final = 1
_RETRY_AFTER_MAX_S: Final = 30  # same as MAX_RETRY_DELAY

# HTTP 403 on these APIs usually signals a UA / firewall policy block
# rather than a transient glitch, so hammering the server with the full
# MAX_RETRY_ATTEMPTS sequence is counter-productive. Allow one retry
# (for the occasional Cloudflare interstitial that resolves on second
# try) and then stop.
_MAX_403_ATTEMPTS: Final = 2

# Chunk size for capped body reads (see ``async_read_capped``).
_READ_CHUNK_BYTES: Final = 64 * 1024


# Longest slice of an error body quoted in an exception message.
_ERROR_EXCERPT_CHARS: Final = 200

# Longest slice of an error body read from the stream for the excerpt.
_ERROR_READ_BYTES: Final = 4096

# An XML or HTML tag, dropped from error excerpts so the readable text fits the cap.
_TAG: Final = re.compile(r"<[^<>]{0,512}>")

# Parameter names whose value is a coordinate or a credential, with an optional "x_" or "access-" style prefix.
_SENSITIVE_NAME: Final = (
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]{1,16}[_.-]){0,2}"
    r"(?:lat|lon|lng|latlng|latitude|longitude|coordinates|location|q|api[_-]?key|key|token|secret|password|auth|appid)"
)

# In order: URL userinfo, a "?name=value" query glued to a path, name=value pairs (also "%3D"), JSON members,
# bare "lat:51.5" numbers, Authorization-style headers.
_REDACTIONS: Final = (
    (re.compile(r"((?:\\?/){2})[^/@\s'\"\\]+@"), r"\1"),
    (re.compile(r"(?<=\S)\?\w[\w.%-]*=[^\s'\"<>]*"), "?<redacted>"),
    (
        re.compile(rf"({_SENSITIVE_NAME}\s*(?:=|%3D)\s*)(?!value\b)[^\s&'\"<>]*", re.IGNORECASE),
        r"\1<redacted>",
    ),
    (
        re.compile(
            r"(\\?\"(?:[\w.-]{0,100}?[_.-])?(?:lat|lon|lng|latitude|longitude|coordinates|api[_-]?key|key|token|secret|password)"
            r"\\?\"\s*:\s*)(\\?\"[^\"\\]*\\?\"|-?[\d.]+)",
            re.IGNORECASE,
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9])((?:lat|lon|lng|latitude|longitude)\s*:\s*)-?\d[\d.]*", re.IGNORECASE),
        r"\1<redacted>",
    ),
    (
        re.compile(
            r"((?:proxy-)?authorization|x-api-key|api-key|x-auth-token)(\s*:\s*)(?:(?:Bearer|Basic|Token|Digest)\s+)?[^\s'\",;<>]+",
            re.IGNORECASE,
        ),
        r"\1\2<redacted>",
    ),
)


class UpstreamResponseError(ValueError):
    """The provider answered, but not with a usable body."""


class UpstreamStatusError(UpstreamResponseError):
    """The provider answered with a status other than 200."""

    def __init__(self, message: str, status: int) -> None:
        """Keep the status for the one caller that tolerates it."""
        super().__init__(message, status)  # both in args so copy and pickle can rebuild it
        self.status = status

    def __str__(self) -> str:
        """Show the message only."""
        return str(self.args[0])


def redact_url_query(text: str) -> str:
    """Remove URL userinfo, query strings and coordinate or key pairs from free text."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_response_error(
    err: aiohttp.ClientResponseError | aiohttp.ConnectionTimeoutError,
) -> aiohttp.ClientError:
    """Rebuild ``err`` of either type without the request URL query (and request headers for a response error)."""
    if not isinstance(err, aiohttp.ClientResponseError):
        return type(err)(redact_url_query(str(err)))
    url = err.request_info.real_url.with_query(None)
    info = aiohttp.RequestInfo(url, err.request_info.method, CIMultiDictProxy(CIMultiDict()), url)
    return aiohttp.ClientResponseError(
        info, (), status=err.status, message=err.message, headers=err.headers,
    )


def require_shape(ok: bool, label: str, what: str) -> None:
    """Raise ``UpstreamResponseError`` when a 200 answer lacks the shape the caller needs."""
    if not ok:
        raise UpstreamResponseError(f"{label}: {what}")


def decode_json_object(raw: str | bytes, label: str) -> dict[str, Any]:
    """Parse ``raw`` as a JSON object, raising ``UpstreamResponseError`` for anything else."""
    try:
        data = json.loads(raw)
    except ValueError as err:
        raise UpstreamResponseError(f"{label} is not valid JSON: {err}") from err
    require_shape(isinstance(data, dict), label, "JSON is not an object")
    return data


def _jittered_backoff(attempt: int) -> float:
    """Return a decorrelated-jitter backoff delay in seconds.

    Uses ``uniform(RETRY_BASE_DELAY, base ** attempt)`` instead of
    ``uniform(0, base ** attempt)``: the latter can return ~0 seconds,
    producing a near-instant retry against a server that is already
    rate-limiting us. A minimum-floor of one base interval keeps the
    retry humane while the upper bound still scales with attempt.
    """
    upper = min(MAX_RETRY_DELAY, float(RETRY_BASE_DELAY ** attempt))
    lower = float(min(RETRY_BASE_DELAY, upper))
    return random.uniform(lower, upper)  # noqa: S311 (jitter, not crypto)


def _parse_retry_after_header(header: str | None) -> float | None:
    """Parse an HTTP ``Retry-After`` header value.

    Accepts either a delay in seconds (``"5"``) or an HTTP-date
    (``"Thu, 01 Jan 2026 00:00:00 GMT"``).

    Args:
        header: Raw header value, or ``None``.

    Returns:
        Seconds to wait (non-negative float), or ``None`` if the
        header is absent or malformed.

    """
    if header is None:
        return None
    # Try seconds format first
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    # Try HTTP-date format
    try:
        parsed = email.utils.parsedate_to_datetime(header)
        now = datetime.now(tz=UTC)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (parsed - now).total_seconds())
    except (ValueError, TypeError):
        return None


def _clamp_retry_delay(seconds: float) -> float:
    """Clamp a retry delay to a safe range.

    Args:
        seconds: Raw delay in seconds.

    Returns:
        Delay clamped to ``[_RETRY_AFTER_MIN_S, _RETRY_AFTER_MAX_S]``.

    """
    return max(_RETRY_AFTER_MIN_S, min(_RETRY_AFTER_MAX_S, seconds))


async def async_fetch_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: aiohttp.ClientTimeout = DEFAULT_FETCH_TIMEOUT,
    source_label: str = "HTTP",
    logger: logging.Logger | None = None,
) -> aiohttp.ClientResponse:
    """Run the retry loop and sanitise the errors it raises (status, redirect loop, connect timeout)."""
    try:
        return await _retry_loop(
            session, url, params=params, headers=headers, timeout=timeout,
            source_label=source_label, logger=logger,
        )
    except (aiohttp.ClientResponseError, aiohttp.ConnectionTimeoutError) as err:
        clean = sanitize_response_error(err)
    # Raised outside the handler so the clean error has no __context__ pointing at the raw one.
    raise clean


async def _retry_loop(  # noqa: C901 (linear retry control flow with status + auth + jitter branches)
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: aiohttp.ClientTimeout = DEFAULT_FETCH_TIMEOUT,
    source_label: str = "HTTP",
    logger: logging.Logger | None = None,
) -> aiohttp.ClientResponse:
    """Perform an HTTP GET with retry on transient errors.

    Retries on HTTP 403, 429, 5xx, ``TimeoutError``, and
    ``aiohttp.ClientConnectionError``.  Does NOT retry on 401.

    Args:
        session: aiohttp client session.
        url: Request URL.
        params: Optional query parameters.
        headers: Optional request headers.
        timeout: Request timeout (per attempt).
        source_label: Label for log messages (e.g. source name).
        logger: Logger instance (defaults to module logger).

    Returns:
        The successful ``aiohttp.ClientResponse``.

    Raises:
        ConfigEntryAuthFailed: On HTTP 401 (never retried).
        aiohttp.ClientResponseError: After all retries exhausted.
        aiohttp.ClientError: On non-retryable client errors.
        TimeoutError: After all retries exhausted on timeout.

    """
    log = logger or _LOGGER
    # Merge in the default User-Agent unless the caller already set one.
    # Several upstreams (NWS, Met Office, Meteoalarm) 403 anonymous UAs.
    effective_headers: dict[str, str] = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        effective_headers.update(headers)
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            response = await session.get(
                url,
                params=params,
                headers=effective_headers,
                timeout=timeout,
            )
            # 401 = permanent auth failure, never retry
            if response.status == 401:
                raise ConfigEntryAuthFailed(
                    f"Authentication failed for {source_label} (HTTP 401)",
                )

            # Transient errors, retry with backoff + jitter
            if response.status in (403, 429) or response.status >= 500:
                # 403 is almost always a UA / IP block rather than a
                # transient glitch; capped below MAX_RETRY_ATTEMPTS.
                attempt_cap = (
                    _MAX_403_ATTEMPTS if response.status == 403
                    else MAX_RETRY_ATTEMPTS
                )
                if attempt < attempt_cap:
                    # On 429, honour Retry-After header if present
                    if response.status == 429:
                        retry_after = _parse_retry_after_header(
                            response.headers.get("Retry-After"),
                        )
                        if retry_after is not None:
                            delay = _clamp_retry_delay(retry_after)
                        else:
                            delay = _jittered_backoff(attempt)
                    else:
                        delay = _jittered_backoff(attempt)
                    log.warning(
                        "%s: HTTP %d on attempt %d/%d, retrying in %.1fs",
                        source_label,
                        response.status,
                        attempt,
                        attempt_cap,
                        delay,
                    )
                    response.release()
                    await asyncio.sleep(delay)
                    continue
                # Final attempt, raise (the public wrapper sanitises it)
                response.raise_for_status()

            return response

        except aiohttp.ClientResponseError:
            raise  # HTTP error responses (401, exhausted retries), propagate
        except (TimeoutError, aiohttp.ClientConnectionError) as err:
            last_err = err
            if attempt < MAX_RETRY_ATTEMPTS:
                delay = _jittered_backoff(attempt)
                log.warning(
                    "%s: %s on attempt %d/%d, retrying in %.1fs",
                    source_label,
                    type(err).__name__,
                    attempt,
                    MAX_RETRY_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise

    # Unreachable when MAX_RETRY_ATTEMPTS >= 1, but satisfies type checker
    msg = f"Retry exhausted for {source_label}"
    raise aiohttp.ClientError(msg) from last_err


async def async_read_capped(
    response: aiohttp.ClientResponse, max_bytes: int,
) -> bytes | None:
    """Read a body in chunks, None if over the cap; ``read(n)`` returns only the buffered part."""
    content_length = response.content_length
    if content_length is not None and content_length > max_bytes:
        return None
    buffer = bytearray()
    async for chunk in response.content.iter_chunked(_READ_CHUNK_BYTES):
        buffer += chunk
        if len(buffer) > max_bytes:
            return None
    return bytes(buffer)


async def _error_excerpt(response: aiohttp.ClientResponse) -> str:
    """Return the start of an error body on one line with URL queries redacted, '' if unreadable."""
    try:
        raw = await response.content.read(_ERROR_READ_BYTES)
    except (aiohttp.ClientError, TimeoutError):
        return ""
    text = raw[:_ERROR_READ_BYTES].decode("utf-8", errors="replace")
    return redact_url_query(" ".join(_TAG.sub(" ", text).split()))[:_ERROR_EXCERPT_CHARS]


@overload
async def async_fetch_checked(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = ...,
    headers: dict[str, str] | None = ...,
    timeout: aiohttp.ClientTimeout = ...,
    source_label: str = ...,
    logger: logging.Logger | None = ...,
    body: Literal["text"] = ...,
    max_bytes: int | None = ...,
) -> str: ...


@overload
async def async_fetch_checked(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = ...,
    headers: dict[str, str] | None = ...,
    timeout: aiohttp.ClientTimeout = ...,
    source_label: str = ...,
    logger: logging.Logger | None = ...,
    body: Literal["json"],
    max_bytes: int | None = ...,
) -> dict[str, Any]: ...


@overload
async def async_fetch_checked(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = ...,
    headers: dict[str, str] | None = ...,
    timeout: aiohttp.ClientTimeout = ...,
    source_label: str = ...,
    logger: logging.Logger | None = ...,
    body: Literal["bytes"],
    max_bytes: int,
) -> bytes: ...


async def async_fetch_checked(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: aiohttp.ClientTimeout = DEFAULT_FETCH_TIMEOUT,
    source_label: str = "HTTP",
    logger: logging.Logger | None = None,
    body: Literal["text", "json", "bytes"] = "text",
    max_bytes: int | None = None,
) -> str | dict[str, Any] | bytes:
    """GET with retry and return a usable 200 body, else raise ``UpstreamResponseError``."""
    response = await async_fetch_with_retry(
        session, url, params=params, headers=headers, timeout=timeout,
        source_label=source_label, logger=logger,
    )
    empty = f"{source_label} returned an empty body"
    async with response:
        if response.status != 200:
            raise UpstreamStatusError(
                f"{source_label} returned HTTP {response.status}: {await _error_excerpt(response)}",
                response.status,
            )
        if body == "bytes":
            if max_bytes is None:
                msg = "max_bytes is required for body='bytes'"
                raise TypeError(msg)
            raw = await async_read_capped(response, max_bytes)
            if raw is None:
                msg = f"{source_label} response exceeded {max_bytes} bytes"
                raise UpstreamResponseError(msg)
            if not raw.strip():
                raise UpstreamResponseError(empty)
            return raw
        text = await response.text()
    if not text.strip():
        raise UpstreamResponseError(empty)
    return decode_json_object(text, source_label) if body == "json" else text
