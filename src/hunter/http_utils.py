"""Shared HTTP client, headers, timeout and retry for scrapers."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
from loguru import logger

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

DEFAULT_TIMEOUT = 20.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds


def get_httpx_client(
    delay_seconds: float = 1.5,
    timeout: float = DEFAULT_TIMEOUT,
    follow_redirects: bool = True,
) -> httpx.Client:
    return httpx.Client(
        headers=DEFAULT_HEADERS,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )


async def rate_limited_get(
    client: httpx.AsyncClient,
    url: str,
    delay_seconds: float = 1.5,
) -> httpx.Response:
    await asyncio.sleep(delay_seconds)
    resp = client.get(url)
    resp.raise_for_status()
    return resp


def sync_get_with_delay(
    client: httpx.Client,
    url: str,
    delay_seconds: float = 1.5,
) -> httpx.Response:
    """GET with rate limit delay. No retry (use sync_get_with_retry for that)."""
    time.sleep(delay_seconds)
    resp = client.get(url)
    resp.raise_for_status()
    return resp


def sync_get_with_retry(
    client: httpx.Client,
    url: str,
    delay_seconds: float = 1.5,
    max_retries: int = MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
) -> httpx.Response:
    """GET with delay and exponential backoff retry (3 retries by default)."""
    time.sleep(delay_seconds)
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = client.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            last_exc = e
            if attempt < max_retries - 1:
                wait = RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning("GET {} attempt {} failed: {}; retry in {:.1f}s", url, attempt + 1, e, wait)
                time.sleep(wait)
    raise last_exc
