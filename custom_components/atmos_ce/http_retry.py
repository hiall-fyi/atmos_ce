"""Shared HTTP GET retry logic for Atmos CE.

Provides ``async_fetch_with_retry``, a single implementation of
exponential-backoff-with-jitter used by both ``WeatherWarningSource``
(alert fetching) and ``OpenMeteoBackend`` (forecast / AQ fetching).
"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import random
from datetime import UTC, datetime
from typing import Any, Final

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed

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


async def async_fetch_with_retry(  # noqa: C901 (linear retry control flow with status + auth + jitter branches)
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
                # Final attempt, raise
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
