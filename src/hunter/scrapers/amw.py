"""AMW (Agencja Mienia Wojskowego) real estate listings — httpx + BeautifulSoup."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS, sync_get_with_retry
from hunter.price_parser import price_pln_from_text
from hunter.schema import normalized_listing
from hunter.scrapers.common import is_likely_error_page

BASE_URL = "https://amw.com.pl"
# Search results: all offers (no filters). Pagination: ,page,N,limit,LIMIT,sort,estate_asc
LIST_PATH = "/pl/nieruchomosci/nieruchomosci-amw/wyniki-wyszukiwania/search,,city,,zone,,company,,category,,dev_forms,;,useful_area_from,,useful_area_to,,surface_from,,surface_to,,surface_unit,ha,price_from,,price_to,"


def _parse_auction_date(text: Optional[str]) -> Optional[datetime]:
    """Parse 'W dniu: 24.02.2026r, godz. 10:00' or '24.02.2026r,godz. 10:00'."""
    if not text:
        return None
    import pytz
    tz = pytz.timezone("Europe/Warsaw")
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})r?\s*,?\s*godz\.?\s*(\d{1,2}):(\d{2})", (text or "").strip())
    if not m:
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", (text or "").strip())
        if not m:
            return None
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = 10, 0
    else:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
    try:
        return tz.localize(datetime(year, month, day, hour, minute))
    except (ValueError, TypeError):
        return None


def _list_page_url(page: int, limit: int = 50) -> str:
    """Build list URL for given page (0-based)."""
    return f"{BASE_URL}{LIST_PATH},page,{page},limit,{limit},sort,estate_asc"


def _parse_list_page(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """
    Parse list page: each offer is under an h2 (location/title), then block with
    Powierzchnia, Cena wywoławcza, Woj., W dniu.
    No detail URLs on list; we build stable source_url from content hash.
    """
    results = []
    # All h2 that look like offer titles (location lines)
    h2s = soup.select("h2")
    for h2 in h2s:
        title = (h2.get_text(strip=True) or "").strip()
        if not title or len(title) < 3:
            continue
        # Skip if it's a section header, not a location
        if title.startswith("Kategoria") or "Województwo" in title or "Lista" in title:
            continue
        block = []
        for sib in h2.find_next_siblings():
            if sib.name == "h2":
                break
            block.append(sib.get_text(strip=True) if hasattr(sib, "get_text") else str(sib))
        text = " ".join(block)
        price_el = h2.find_next(string=re.compile(r"Cena\s+wywo[łl]awcza\s*(\d[\d\s]*)", re.I))
        price_str = None
        if price_el:
            parent = price_el.parent
            if parent:
                price_str = parent.get_text(strip=True) if hasattr(parent, "get_text") else str(parent)
        if not price_str:
            m = re.search(r"Cena\s+wywo[łl]awcza\s*([\d\s]+)\s*PLN", text, re.I)
            price_str = m.group(0) if m else None
        price_pln = price_pln_from_text(price_str)
        region = None
        rm = re.search(r"Woj\.?:\s*([^\s,]+(?:\s+[^\s,]+)?)", text)
        if rm:
            region = rm.group(1).strip()
        date_str = None
        dm = re.search(r"W\s+dniu:\s*[\d.]+\s*r?\s*,?\s*godz\.?\s*[\d:]+", text, re.I)
        if dm:
            date_str = dm.group(0)
        auction_date = _parse_auction_date(date_str)
        city = title.split(",")[0].strip() if "," in title else title.strip()
        location = title
        # Stable unique id for upsert (no detail URL on AMW list)
        raw_id = f"{title}|{price_pln or 0}|{auction_date.isoformat() if auction_date else ''}"
        hash_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
        source_url = f"{BASE_URL}/pl/nieruchomosci/nieruchomosci-amw/#{hash_id}"
        if is_likely_error_page(title, None):
            continue
        results.append({
            "title": f"Nieruchomość AMW — {title}",
            "description": f"Powierzchnia / Cena wywoławcza w ofercie AMW. {text[:1500]}",
            "price_pln": price_pln,
            "location": location,
            "city": city,
            "source_url": source_url,
            "auction_date": auction_date,
            "region": region,
            "raw_data": {"price_raw": price_str, "snippet": text[:500]},
        })
    return results


def scrape_amw(config: Optional[dict] = None) -> list[dict[str, Any]]:
    """Scrape AMW search results. Uses list pages only (no detail pages)."""
    cfg = config or {}
    scraping = cfg.get("scraping", {})
    delay = float(scraping.get("httpx_delay_seconds", 1.5))
    max_pages = int(scraping.get("max_pages_auctions", 50))
    max_listings = scraping.get("max_listings")
    limit_per_page = 50
    results = []
    seen_urls = set()
    with httpx.Client(headers=DEFAULT_HEADERS, timeout=60.0, follow_redirects=True) as client:
        for page in range(max_pages):
            list_url = _list_page_url(page, limit=limit_per_page)
            try:
                resp = sync_get_with_retry(client, list_url, delay)
                soup = BeautifulSoup(resp.text, "html.parser")
                items = _parse_list_page(soup)
                logger.info("AMW list page {}: {} offers", page + 1, len(items))
                if not items:
                    break
                for item in items:
                    if item["source_url"] in seen_urls:
                        continue
                    seen_urls.add(item["source_url"])
                    row = normalized_listing(
                        title=item["title"],
                        description=item.get("description"),
                        price_pln=item.get("price_pln"),
                        location=item["location"],
                        city=item["city"],
                        source="amw",
                        source_url=item["source_url"],
                        auction_date=item.get("auction_date"),
                        images=[],
                        raw_data=item.get("raw_data"),
                        region=item.get("region"),
                    )
                    results.append(row)
                    if max_listings is not None and len(results) >= int(max_listings):
                        return results
            except httpx.HTTPError as e:
                logger.error("AMW list page {} failed: {}", page + 1, e)
                break
    return results
