"""OLX.pl — httpx + BeautifulSoup. Classifieds list + detail."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS, sync_get_with_delay
from hunter.price_parser import price_pln_from_text
from hunter.schema import normalized_listing

BASE_URL = "https://www.olx.pl"
# Real estate category (dom, mieszkania, dzialki)
SEARCH_URL = f"{BASE_URL}/nieruchomosci/"


def _parse_list_page(soup: BeautifulSoup, base: str) -> list[str]:
    urls = []
    for a in soup.select("a[href*='/d/oferta/']"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base, href)
        if "otodom.pl" in full:
            continue
        if "olx.pl" in full and "/d/oferta/" in full:
            urls.append(full.split("?")[0])
    return list(dict.fromkeys(urls))


def _parse_detail(html: str, url: str) -> Optional[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    raw = {"url": url, "title": None, "description": None, "price": None, "location": None, "images": []}

    raw["title"] = (soup.select_one("h1, [data-cy='ad_title']") or None)
    raw["title"] = raw["title"].get_text(strip=True) if raw["title"] else ""
    raw["description"] = (soup.select_one("[data-cy='ad_description'], .description") or None)
    raw["description"] = raw["description"].get_text(strip=True)[:5000] if raw["description"] else None
    raw["price"] = (soup.select_one("[data-cy='ad_price'], [class*='price']") or None)
    raw["price"] = raw["price"].get_text(strip=True) if raw["price"] else None
    raw["location"] = (soup.select_one("[data-cy='ad_location'], [class*='location']") or None)
    raw["location"] = raw["location"].get_text(strip=True) if raw["location"] else ""

    for img in soup.select("img[src*='olx'], [data-cy='adPhotos'] img"):
        src = img.get("src") or img.get("data-src")
        if src:
            raw["images"].append(urljoin(url, src))

    title = raw["title"] or "Oferta OLX"
    price_pln = price_pln_from_text(raw["price"])
    location = (raw["location"] or "").strip() or "Polska"
    city = location.split(",")[0].strip() if location else "Polska"

    return normalized_listing(
        title=title,
        description=raw["description"],
        price_pln=price_pln,
        location=location,
        city=city,
        source="olx",
        source_url=url,
        auction_date=None,
        images=raw["images"],
        raw_data=raw,
    )


def scrape_olx(config: Optional[dict] = None) -> list[dict[str, Any]]:
    cfg = config or {}
    scraping = cfg.get("scraping", {})
    delay = float(scraping.get("httpx_delay_seconds", 1.5))
    max_pages = int(scraping.get("max_pages_classifieds", 10))

    results = []
    with httpx.Client(headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            list_url = f"{SEARCH_URL}?page={page}" if page > 1 else SEARCH_URL
            try:
                resp = sync_get_with_delay(client, list_url, delay)
                soup = BeautifulSoup(resp.text, "html.parser")
                urls = _parse_list_page(soup, BASE_URL)
                if not urls:
                    break
                for detail_url in urls:
                    try:
                        r = sync_get_with_delay(client, detail_url, delay)
                        row = _parse_detail(r.text, detail_url)
                        if row:
                            results.append(row)
                    except Exception as e:
                        logger.warning("Skip OLX listing {}: {}", detail_url, e)
            except httpx.HTTPError as e:
                logger.error("OLX list page failed: {}", e)
                break
    return results
