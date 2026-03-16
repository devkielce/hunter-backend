"""Court auctions: elicytacje.komornik.pl (System elektronicznych licytacji) — httpx + Playwright."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS, sync_get_with_retry
from hunter.price_parser import price_pln_from_full_text, price_pln_from_text
from hunter.schema import normalized_listing
from hunter.scrapers.common import is_likely_error_page
from hunter.title_extractor import extract_short_title, extract_surface_m2

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


def _extract_city(location: str) -> str:
    """Heuristic: first comma-separated part or whole if short (same as komornik)."""
    if not location:
        return "Polska"
    parts = [p.strip() for p in location.split(",")]
    return parts[0] if parts else location


def _extract_region_from_location(location: str) -> Optional[str]:
    """Extract województwo from location e.g. 'Kielce (świętokrzyskie)' -> 'świętokrzyskie'."""
    if not location or "(" not in location or ")" not in location:
        return None
    start = location.index("(") + 1
    end = location.index(")")
    return location[start:end].strip() or None


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


_STEALTH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_STEALTH_INIT_SCRIPT = 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'


async def _fetch_one_detail_playwright(ctx: Any, url: str, delay_seconds: float) -> Optional[str]:
    """Load one detail page with Playwright (Nuxt SPA); return rendered HTML or None."""
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(delay_seconds)
        # Wait for Nuxt to hydrate — look for the content section
        try:
            await page.wait_for_selector(
                ".content .group, .auction__title, .sidebar",
                timeout=10000,
            )
        except Exception:
            pass
        await asyncio.sleep(0.5)
        return await page.content()
    except Exception as e:
        logger.warning("E-licytacje Playwright detail {} failed: {}", url[:60], e)
        return None
    finally:
        await page.close()


async def _fetch_detail_pages_playwright(
    urls: list[str],
    delay_seconds: float,
) -> dict[str, str]:
    """Load many detail pages with one stealth browser; return dict url -> html."""
    from playwright.async_api import async_playwright

    result: dict[str, str] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(user_agent=_STEALTH_UA)
        await ctx.add_init_script(_STEALTH_INIT_SCRIPT)
        try:
            for url in urls:
                html = await _fetch_one_detail_playwright(ctx, url, delay_seconds)
                if html:
                    result[url] = html
        finally:
            await browser.close()
    return result


def _parse_groups(soup: BeautifulSoup) -> dict[str, dict[str, str]]:
    """Parse .content .group sections into {header: {label: value, ...}}."""
    groups: dict[str, dict[str, str]] = {}
    for grp in soup.select(".content .group"):
        texts = grp.select(".cds-text")
        if not texts:
            continue
        header_el = grp.select_one(".group__header")
        header = header_el.get_text(strip=True) if header_el else ""
        pairs: dict[str, str] = {}
        body_texts = [t for t in texts if "group__header" not in (t.get("class") or [])]
        i = 0
        while i < len(body_texts) - 1:
            cls = " ".join(body_texts[i].get("class") or [])
            if "body-medium" in cls:
                label = body_texts[i].get_text(strip=True)
                value = body_texts[i + 1].get_text(strip=True)
                pairs[label] = value
                i += 2
            else:
                i += 1
        # If only one text without pairs, store it as description
        if not pairs and len(body_texts) == 1:
            pairs["_text"] = body_texts[0].get_text(strip=True)
        groups[header] = pairs
    return groups


def _parse_detail(html: str, url: str) -> Optional[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    # Check for WAF block page
    title_tag = soup.select_one("title")
    if title_tag and "zablokowana" in (title_tag.get_text() or "").lower():
        logger.warning("E-licytacje detail {} blocked by WAF", url[:60])
        return None

    raw: dict[str, Any] = {"url": url, "title": None, "description": None, "price": None,
                           "location": None, "date": None, "images": []}

    # Title: .auction__title
    title_el = soup.select_one(".auction__title")
    raw["title"] = title_el.get_text(strip=True) if title_el else ""

    # Parse structured groups
    groups = _parse_groups(soup)

    # Description from "Opis sprzedawanej nieruchomości" group
    for header, pairs in groups.items():
        if "opis" in header.lower():
            raw["description"] = pairs.get("_text", "")[:5000] or None
            break

    # Price from "Dane licytacji" group -> "Cena wywołania"
    dane_lic = groups.get("Dane licytacji", {})
    raw["price"] = dane_lic.get("Cena wywołania")

    # Date from "Dane licytacji" -> "Data rozpoczęcia"
    raw["date"] = dane_lic.get("Data rozpoczęcia")

    # Location from "Adres nieruchomości" group
    adres_grp = groups.get("Adres nieruchomości", {})
    region = adres_grp.get("Województwo")
    city_raw = adres_grp.get("Miasto", "")
    address_raw = adres_grp.get("Adres", "")
    if address_raw and city_raw:
        location = f"{address_raw}, {city_raw}"
    elif city_raw:
        location = city_raw
    elif address_raw:
        location = address_raw
    else:
        location = "Polska"
    raw["location"] = location

    # Images (skip base64 data URIs)
    for img in soup.select("img[src]"):
        src = img.get("src", "")
        if src and not src.startswith("data:") and ("upload" in src or "image" in src or "photo" in src):
            raw["images"].append(urljoin(url, src))

    combined_text = f"{raw['title'] or ''} {raw['description'] or ''}".strip()
    surface_m2 = extract_surface_m2(combined_text)
    if surface_m2 is not None:
        raw["surface_m2"] = surface_m2
    title = extract_short_title(
        combined_text,
        fallback=raw["title"] or "Licytacja sądowa",
    )
    if is_likely_error_page(raw["title"], raw["description"]):
        return None
    price_pln = price_pln_from_text(raw["price"])
    if price_pln is None:
        full_text = soup.get_text(separator=" ", strip=True) if soup.body else (raw["description"] or "")
        price_pln = price_pln_from_full_text(full_text)
    city = _extract_city(city_raw or location)
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
        region=region,
    )


def _stub_listing_from_item(item: dict[str, str]) -> dict[str, Any]:
    """Minimal listing from list page when detail parse fails; saved to DB so run.py can try fetch_price_from_url."""
    url = (item.get("url") or "").strip()
    if not url:
        raise ValueError("stub listing requires url")
    title = (item.get("title") or "").strip() or "Licytacja sądowa"
    return normalized_listing(
        title=title,
        description=None,
        price_pln=None,
        location="Polska",
        city="Polska",
        source="e_licytacje",
        source_url=url,
        auction_date=None,
        images=[],
        raw_data={"stub_from_list": True},
        region=None,
    )


def _cutoff_for_days_back(days: int) -> Optional[datetime]:
    if days is None or days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def scrape_elicytacje(config: Optional[dict] = None) -> list[dict[str, Any]]:
    cfg = config or {}
    scraping = cfg.get("scraping", {})
    delay = float(scraping.get("httpx_delay_seconds", 1.5))
    pw_delay = float(scraping.get("playwright_delay_seconds", 4.0))
    max_pages = int(scraping.get("max_pages_auctions", 50))
    max_listings = scraping.get("max_listings")  # e.g. on-demand run cap (20); None = no limit
    days_back = scraping.get("days_back")
    cutoff = _cutoff_for_days_back(int(days_back)) if days_back is not None else None
    # Allow custom list URL with region filter (e.g. &voivodeship=MAZOWIECKIE)
    base_list_url = scraping.get("elicytacje_list_url") or LIST_URL

    # --- Phase 1: collect detail URLs from list pages (httpx is fine for list pages) ---
    all_items: list[dict[str, str]] = []
    with httpx.Client(headers=DEFAULT_HEADERS, timeout=60.0, follow_redirects=True) as client:
        page = 1
        while page <= max_pages:
            list_url = f"{base_list_url}&page={page}" if page > 1 else base_list_url
            try:
                resp = sync_get_with_retry(client, list_url, delay)
                soup = BeautifulSoup(resp.text, "html.parser")
                items = _parse_list_page(soup, BASE_URL)
                logger.info("E-licytacje list page {}: {} links", page, len(items))
                if not items:
                    if page == 1:
                        logger.warning(
                            "E-licytacje: no links on first page (check region or site structure)"
                        )
                    break
                all_items.extend(items)
                if max_listings is not None and len(all_items) >= int(max_listings):
                    break
                page += 1
            except httpx.HTTPError as e:
                logger.error("E-licytacje list failed: {}", e)
                break

    to_fetch = all_items
    if max_listings is not None:
        to_fetch = all_items[: int(max_listings)]

    if not to_fetch:
        return []

    # --- Phase 2: fetch detail pages with Playwright (Nuxt SPA) ---
    urls = [item["url"] for item in to_fetch]
    logger.info("E-licytacje: fetching {} detail pages with Playwright", len(urls))
    detail_htmls = asyncio.run(_fetch_detail_pages_playwright(urls, pw_delay))
    logger.info("E-licytacje: got {} rendered pages", len(detail_htmls))

    results: list[dict[str, Any]] = []
    for item in to_fetch:
        html = detail_htmls.get(item["url"])
        row = None
        if html:
            try:
                row = _parse_detail(html, item["url"])
            except Exception as e:
                logger.warning("Parse listing {}: {} (saving stub)", item["url"][:60], e)
        if row:
            ad_str = row.get("auction_date")
            if cutoff is not None and ad_str:
                try:
                    ad = datetime.fromisoformat(ad_str.replace("Z", "+00:00"))
                    if not ad.tzinfo:
                        ad = ad.replace(tzinfo=timezone.utc)
                    if ad.astimezone(timezone.utc) < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            results.append(row)
        else:
            results.append(_stub_listing_from_item(item))
        if max_listings is not None and len(results) >= int(max_listings):
            break
    return results
