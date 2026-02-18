"""Court auctions: elicytacje.komornik.pl (System elektronicznych licytacji) — httpx + BeautifulSoup."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS, sync_get_with_retry
from hunter.price_parser import price_pln_from_text
from hunter.schema import normalized_listing

# Official portal (Krajowa Rada Komornicza); elicytacje.ms.gov.pl no longer resolves
BASE_URL = "https://elicytacje.komornik.pl"
# Nieruchomości, sort by date
LIST_URL = f"{BASE_URL}/wyszukiwarka-licytacji?mainCategory=REAL_ESTATE&sort=dateCreated%2CDESC"


def _parse_auction_date(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    import pytz
    tz = pytz.timezone("Europe/Warsaw")
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(text.strip()[:19], fmt)
            return tz.localize(dt)
        except (ValueError, TypeError):
            continue
    return None


def _parse_list_page(soup: BeautifulSoup, base: str) -> list[dict[str, str]]:
    items = []
    for a in soup.select("a[href*='/licytacje/']"):
        href = a.get("href")
        if not href:
            continue
        full_url = urljoin(base, href)
        if "elicytacje.komornik.pl" not in full_url or "/licytacje/" not in full_url:
            continue
        title = (a.get_text(strip=True) or "").strip() or "E-licytacja"
        items.append({"url": full_url.split("?")[0], "title": title})
    seen: set[str] = set()
    unique = []
    for x in items:
        if x["url"] not in seen:
            seen.add(x["url"])
            unique.append(x)
    return unique


def _parse_detail(html: str, url: str) -> Optional[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    raw = {"url": url, "title": None, "description": None, "price": None, "location": None, "date": None, "images": []}
    raw["title"] = (soup.select_one("h1, .title, [class*='title']") or soup.find("title"))
    raw["title"] = raw["title"].get_text(strip=True) if raw["title"] else ""
    raw["description"] = (soup.select_one(".description, .content, [class*='opis']") or None)
    raw["description"] = raw["description"].get_text(strip=True)[:5000] if raw["description"] else None
    raw["price"] = (soup.select_one("[class*='price'], [class*='cena'], .wartosc") or None)
    raw["price"] = raw["price"].get_text(strip=True) if raw["price"] else None
    raw["location"] = (soup.select_one("[class*='location'], [class*='address'], [class*='sad']") or None)
    raw["location"] = raw["location"].get_text(strip=True) if raw["location"] else ""
    raw["date"] = (soup.select_one("[class*='date'], [class*='termin']") or None)
    raw["date"] = raw["date"].get_text(strip=True) if raw["date"] else None
    for img in soup.select("img[src]"):
        src = img.get("src")
        if src and ("upload" in src or "image" in src or "photo" in src):
            raw["images"].append(urljoin(url, src))

    title = raw["title"] or "Licytacja sądowa"
    price_pln = price_pln_from_text(raw["price"])
    location = (raw["location"] or "").strip() or "Polska"
    city = (location.split(",")[0].strip() if location else "Polska")
    auction_date = _parse_auction_date(raw["date"])

    return normalized_listing(
        title=title,
        description=raw["description"],
        price_pln=price_pln,
        location=location,
        city=city,
        source="e_licytacje",
        source_url=url,
        auction_date=auction_date,
        images=raw["images"],
        raw_data=raw,
    )


def scrape_elicytacje(config: Optional[dict] = None) -> list[dict[str, Any]]:
    cfg = config or {}
    scraping = cfg.get("scraping", {})
    delay = float(scraping.get("httpx_delay_seconds", 1.5))
    max_pages = int(scraping.get("max_pages_auctions", 50))

    results = []
    with httpx.Client(headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True) as client:
        page = 1
        while page <= max_pages:
            list_url = f"{LIST_URL}&page={page}" if page > 1 else LIST_URL
            try:
                resp = sync_get_with_retry(client, list_url, delay)
                soup = BeautifulSoup(resp.text, "html.parser")
                items = _parse_list_page(soup, BASE_URL)
                if not items:
                    break
                for item in items:
                    try:
                        r = sync_get_with_retry(client, item["url"], delay)
                        row = _parse_detail(r.text, item["url"])
                        if row:
                            results.append(row)
                    except Exception as e:
                        logger.warning("Skip listing {}: {}", item["url"], e)
                page += 1
            except httpx.HTTPError as e:
                logger.error("E-licytacje list failed: {}", e)
                break
    return results
