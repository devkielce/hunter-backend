"""
When price is missing on the main page, try to get it from a linked page (e.g. Facebook post → arcabinvestments.com).
Used by Facebook (Apify) normalizer; optional for other sources.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS, sync_get_with_retry
from hunter.price_parser import price_pln_from_full_text

# URL regex (simple; avoids trailing punctuation)
_URL_RE = re.compile(
    r"https?://[^\s<>\"'\]]+",
    re.I,
)

# Domains we skip when looking for "offer" links (social, tracking)
_SKIP_DOMAINS = frozenset(
    ("facebook.com", "fb.com", "fb.me", "instagram.com", "twitter.com", "x.com", "linkedin.com")
)


def extract_first_offer_url(
    text: str,
    allowed_domains: Optional[list[str]] = None,
) -> Optional[str]:
    """
    Find first https URL in text that looks like an offer page.
    If allowed_domains is set, return first URL whose host is in the list; else first URL not in _SKIP_DOMAINS.
    """
    if not text or not text.strip():
        return None
    for m in _URL_RE.finditer(text):
        raw = m.group(0).rstrip(".,;:)")
        try:
            parsed = urlparse(raw)
            if not parsed.netloc or parsed.scheme not in ("http", "https"):
                continue
            host = parsed.netloc.lower().replace("www.", "")
            if allowed_domains:
                if any(d in host or host.endswith("." + d) for d in allowed_domains):
                    return raw
            else:
                if not any(skip in host for skip in _SKIP_DOMAINS):
                    return raw
        except Exception:
            continue
    return None


def fetch_price_from_url(
    url: str,
    client: httpx.Client,
    delay: float = 1.0,
    timeout: float = 10.0,
) -> Optional[int]:
    """
    GET url, parse HTML, extract price from full text (price_pln_from_full_text).
    Returns price in grosze or None.
    """
    try:
        resp = sync_get_with_retry(client, url, delay_seconds=delay, timeout=timeout)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        body = soup.body or soup
        full_text = body.get_text(separator=" ", strip=True) if body else ""
        price_pln = price_pln_from_full_text(full_text)
        if price_pln is not None:
            logger.debug("Price from followed link {}: {} grosze", url[:60], price_pln)
        return price_pln
    except Exception as e:
        logger.warning("Failed to fetch price from link {}: {}", url[:60], e)
        return None
