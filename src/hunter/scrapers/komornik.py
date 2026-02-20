"""Bailiff auctions: licytacje.komornik.pl — httpx + BeautifulSoup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS, sync_get_with_retry
from hunter.price_parser import price_pln_from_text
from hunter.schema import normalized_listing
from hunter.scrapers.common import is_likely_error_page

# Oficjalny serwis Krajowej Rady Komorniczej — jedyne źródło dla tego scrapera
BASE_URL = "https://licytacje.komornik.pl"
# Real estate categories: 30=mieszkania, 29=domy, 31=garaze, 32=grunty, 33=lokale, 34=magazyny, 35=inne, 36=statki
# Use Filter/30 for mieszkania (apartments) as main list; paginate with ?page=
FILTER_NIERUCHOMOSCI = f"{BASE_URL}/Notice/Filter/30"


def _parse_auction_date(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    import pytz
    tz = pytz.timezone("Europe/Warsaw")
    # Common formats: "2024-03-15 10:00", "15.03.2024 10:00"
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(text.strip()[:19], fmt)
            return tz.localize(dt)
        except (ValueError, TypeError):
            continue
    return None


def _parse_list_page(
    soup: BeautifulSoup,
    base: str,
    region_filter: Optional[str] = None,
) -> list[dict[str, str]]:
    """
    Extract listing links from Notice/Filter page.
    Table columns: 0=Lp, 1=photo, 2=date, 3=Nazwa, 4=Miasto (Województwo), 5=Cena, 6=?, 7=Więcej link.
    If region_filter is set (e.g. 'świętokrzyskie'), only include rows where column 4 contains it.
    """
    items = []
    region_lower = (region_filter or "").strip().lower()
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue
        miasto_woj = (tds[4].get_text(strip=True) or "").lower()
        if region_lower and region_lower not in miasto_woj:
            continue
        a = tds[7].find("a", href=lambda h: h and "Notice/Details" in h)
        if not a:
            continue
        href = a.get("href")
        if not href:
            continue
        full_url = urljoin(base, href)
        if "licytacje.komornik.pl" not in full_url or "Details" not in full_url:
            continue
        title = (tds[3].get_text(strip=True) or "").strip() or "Licytacja komornicza"
        # Column 4 is "Miasto (Województwo)" e.g. "Suwałki  (podlaskie)" — extract region for frontend filtering
        raw_miasto_woj = (tds[4].get_text(strip=True) or "")
        region = None
        if "(" in raw_miasto_woj and ")" in raw_miasto_woj:
            region = raw_miasto_woj[raw_miasto_woj.index("(") + 1 : raw_miasto_woj.index(")")].strip()
        items.append({"url": full_url, "title": title, "region": region})
    seen: set[str] = set()
    return [x for x in items if x["url"] not in seen and (seen.add(x["url"]) or True)]


def _parse_detail_page(html: str, url: str) -> Optional[dict[str, Any]]:
    """Parse one detail page into normalized listing or None."""
    soup = BeautifulSoup(html, "html.parser")
    raw = {"url": url, "title": None, "description": None, "price": None, "location": None, "date": None, "images": []}

    title_el = soup.select_one("h1, .title, .auction-title, [class*='title']")
    raw["title"] = title_el.get_text(strip=True) if title_el else ""
    desc_el = soup.select_one(".description, .content, [class*='description'], [class*='content']")
    raw["description"] = desc_el.get_text(strip=True)[:5000] if desc_el else None
    price_el = soup.select_one("[class*='price'], [class*='cena'], .value")
    raw["price"] = price_el.get_text(strip=True) if price_el else None
    loc_el = soup.select_one("[class*='location'], [class*='address'], [class*='miejsce']")
    raw["location"] = loc_el.get_text(strip=True) if loc_el else ""
    date_el = soup.select_one("[class*='date'], [class*='termin'], [class*='auction-date']")
    raw["date"] = date_el.get_text(strip=True) if date_el else None
    for img in soup.select("img[src*='upload'], img[src*='image']"):
        src = img.get("src")
        if src:
            raw["images"].append(urljoin(url, src))

    title = raw["title"] or "Licytacja komornicza"
    if is_likely_error_page(raw["title"], raw["description"]):
        return None
    price_pln = price_pln_from_text(raw["price"])
    location = (raw["location"] or "").strip() or "Polska"
    city = _extract_city(location)
    auction_date = _parse_auction_date(raw["date"])

    return normalized_listing(
        title=title,
        description=raw["description"],
        price_pln=price_pln,
        location=location,
        city=city,
        source="komornik",
        source_url=url,
        auction_date=auction_date,
        images=raw["images"] or [],
        raw_data=raw,
    )


def _extract_city(location: str) -> str:
    """Heuristic: first comma-separated part or whole if short."""
    if not location:
        return "Polska"
    parts = [p.strip() for p in location.split(",")]
    return parts[0] if parts else location


# Default: all regions (no filter). Set komornik_region in config to e.g. "świętokrzyskie" to limit.
DEFAULT_KOMMORNIK_REGION = ""


def _cutoff_for_days_back(days: int) -> Optional[datetime]:
    """Return cutoff datetime (UTC) for listings older than this are skipped. None if days_back not used."""
    if days is None or days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def scrape_komornik(config: Optional[dict] = None) -> list[dict[str, Any]]:
    cfg = config or {}
    scraping = cfg.get("scraping", {})
    delay = float(scraping.get("httpx_delay_seconds", 1.5))
    max_pages = int(scraping.get("max_pages_auctions", 50))
    max_listings = scraping.get("max_listings")  # e.g. on-demand run cap (20); None = no limit
    # Only use default when key is missing; explicit "" means "all regions"
    region_val = scraping.get("komornik_region")
    if region_val is None:
        region = (DEFAULT_KOMMORNIK_REGION or "").strip() or None
    else:
        region = (region_val or "").strip() or None
    days_back = scraping.get("days_back")
    cutoff = _cutoff_for_days_back(int(days_back)) if days_back is not None else None

    results = []
    with httpx.Client(headers=DEFAULT_HEADERS, timeout=60.0, follow_redirects=True) as client:
        page = 1
        stop_early = False
        while page <= max_pages and not stop_early:
            list_url = f"{FILTER_NIERUCHOMOSCI}?page={page}" if page > 1 else FILTER_NIERUCHOMOSCI
            try:
                resp = sync_get_with_retry(client, list_url, delay)
                soup = BeautifulSoup(resp.text, "html.parser")
                items = _parse_list_page(soup, BASE_URL, region_filter=region)
                logger.info("Komornik list page {}: {} links", page, len(items))
                if not items:
                    if page == 1:
                        logger.warning(
                            "Komornik: no links on first page (check region or site structure)"
                        )
                    break
                for item in items:
                    try:
                        r = sync_get_with_retry(client, item["url"], delay)
                        row = _parse_detail_page(r.text, item["url"])
                        if row:
                            if item.get("region") is not None:
                                row["region"] = item["region"]
                            ad_str = row.get("auction_date")
                            if cutoff is not None and ad_str:
                                try:
                                    ad = datetime.fromisoformat(ad_str.replace("Z", "+00:00"))
                                    if not ad.tzinfo:
                                        ad = ad.replace(tzinfo=timezone.utc)
                                    if ad.astimezone(timezone.utc) < cutoff:
                                        stop_early = True
                                        break
                                except (ValueError, TypeError):
                                    pass
                            results.append(row)
                            if max_listings is not None and len(results) >= int(max_listings):
                                stop_early = True
                                break
                    except Exception as e:
                        logger.warning("Skip listing {}: {}", item["url"], e)
                page += 1
            except httpx.HTTPError as e:
                logger.error("Komornik list page failed: {}", e)
                break
    return results
