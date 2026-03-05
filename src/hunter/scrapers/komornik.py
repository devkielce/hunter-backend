"""Bailiff auctions: licytacje.komornik.pl — list and detail via Playwright when JS-rendered."""
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

# Oficjalny serwis Krajowej Rady Komorniczej
BASE_URL = "https://licytacje.komornik.pl"
# 30=mieszkania; listę i szczegóły pobieramy z obecnej struktury (obwieszczenia-o-licytacji)
FILTER_NIERUCHOMOSCI = f"{BASE_URL}/Notice/Filter/30"
# Nowa struktura linków (strona zmieniła się z Notice/Details na wyszukiwarka/obwieszczenia-o-licytacji)
DETAIL_LINK_HREF = "obwieszczenia-o-licytacji"


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


def _parse_list_page_from_soup(soup: BeautifulSoup, base: str) -> list[dict[str, str]]:
    """Extract listing links from list page (table or card links). No region filter."""
    items: list[dict[str, str]] = []
    # Stara struktura: tabela z linkami Notice/Details
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue
        a = tds[7].find("a", href=lambda h: h and ("Notice/Details" in (h or "") or DETAIL_LINK_HREF in (h or "")))
        if not a:
            continue
        href = a.get("href")
        if not href:
            continue
        full_url = urljoin(base, href)
        if "licytacje.komornik.pl" not in full_url:
            continue
        if "Details" not in full_url and DETAIL_LINK_HREF not in full_url:
            continue
        title = (tds[3].get_text(strip=True) or "").strip() or "Licytacja komornicza"
        raw_miasto_woj = (tds[4].get_text(strip=True) or "")
        region = None
        if "(" in raw_miasto_woj and ")" in raw_miasto_woj:
            region = raw_miasto_woj[raw_miasto_woj.index("(") + 1 : raw_miasto_woj.index(")")].strip()
        items.append({"url": full_url, "title": title, "region": region})
    # Nowa struktura: linki obwieszczenia-o-licytacji (karty, bez tabeli)
    if not items:
        for a in soup.select(f'a[href*="{DETAIL_LINK_HREF}"]'):
            href = a.get("href")
            if not href:
                continue
            full_url = urljoin(base, href)
            if "licytacje.komornik.pl" not in full_url or DETAIL_LINK_HREF not in full_url:
                continue
            title = (a.get_text(strip=True) or "").strip() or "Licytacja komornicza"
            items.append({"url": full_url, "title": title, "region": None})
    seen: set[str] = set()
    return [x for x in items if x["url"] not in seen and (seen.add(x["url"]) or True)]


async def _fetch_list_items_playwright(
    list_url: str,
    page_num: int,
    delay_seconds: float,
) -> list[dict[str, str]]:
    """Load list page with Playwright (Vue/Nuxt), return [{url, title, region}, ...]. Filter by region in app."""
    from playwright.async_api import async_playwright

    url = f"{list_url}?page={page_num}" if page_num > 1 else list_url
    items: list[dict[str, str]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(delay_seconds)
            try:
                await page.wait_for_selector(f'a[href*="{DETAIL_LINK_HREF}"]', timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(0.5)
            html = await page.content()
            await page.close()
        finally:
            await browser.close()
    soup = BeautifulSoup(html, "html.parser")
    items = _parse_list_page_from_soup(soup, BASE_URL)
    if not items:
        # Fallback: linki obwieszczenia-o-licytacji
        for a in soup.select(f'a[href*="{DETAIL_LINK_HREF}"]'):
            href = a.get("href")
            if not href:
                continue
            full_url = urljoin(BASE_URL, href)
            if "licytacje.komornik.pl" not in full_url or DETAIL_LINK_HREF not in full_url:
                continue
            title = (a.get_text(strip=True) or "").strip() or "Licytacja komornicza"
            items.append({"url": full_url, "title": title, "region": None})
        seen = set()
        items = [x for x in items if x["url"] not in seen and (seen.add(x["url"]) or True)]
    return items


async def _fetch_one_detail_playwright(browser: Any, url: str, delay_seconds: float) -> Optional[str]:
    """Load one detail page with Playwright; return HTML or None."""
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(delay_seconds)
        try:
            await page.wait_for_selector("body", timeout=5000)
        except Exception:
            pass
        return await page.content()
    except Exception as e:
        logger.warning("Komornik Playwright detail {} failed: {}", url[:60], e)
        return None
    finally:
        await page.close()


async def _fetch_detail_pages_playwright(
    urls: list[str],
    delay_seconds: float,
) -> dict[str, str]:
    """Load many detail pages with one browser; return dict url -> html."""
    from playwright.async_api import async_playwright

    result: dict[str, str] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for url in urls:
                html = await _fetch_one_detail_playwright(browser, url, delay_seconds)
                if html:
                    result[url] = html
        finally:
            await browser.close()
    return result


def _parse_detail_page(html: str, url: str) -> Optional[dict[str, Any]]:
    """Parse one detail page into normalized listing or None."""
    soup = BeautifulSoup(html, "html.parser")
    raw = {"url": url, "title": None, "description": None, "price": None, "location": None, "date": None, "images": []}

    title_el = soup.select_one("h1, .title, .auction-title, [class*='title']")
    raw["title"] = title_el.get_text(strip=True) if title_el else ""
    if not raw["title"]:
        for tag in soup.find_all(["h1", "h2", "h3"], limit=1):
            raw["title"] = tag.get_text(strip=True) or ""
            break
    desc_el = soup.select_one(".description, .content, [class*='description'], [class*='content']")
    raw["description"] = desc_el.get_text(strip=True)[:5000] if desc_el else None
    if not raw["description"] and soup.body:
        raw["description"] = soup.body.get_text(separator=" ", strip=True)[:5000]
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

    combined_text = f"{raw['title'] or ''} {raw['description'] or ''}".strip()
    surface_m2 = extract_surface_m2(combined_text)
    if surface_m2 is not None:
        raw["surface_m2"] = surface_m2
    title = extract_short_title(
        combined_text,
        fallback=raw["title"] or "Licytacja komornicza",
    )
    if is_likely_error_page(raw["title"], raw["description"]):
        return None
    price_pln = price_pln_from_text(raw["price"])
    if price_pln is None:
        preview = soup.select_one("#Preview, .schema-preview, [id*='review']") or soup.body
        full_text = preview.get_text(separator=" ", strip=True) if preview else (raw["description"] or "")
        price_pln = price_pln_from_full_text(full_text)
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


def _stub_listing_from_item(item: dict[str, str], source: str = "komornik") -> dict[str, Any]:
    """Minimal listing from list page when detail parse fails; saved to DB so run.py can try fetch_price_from_url."""
    url = (item.get("url") or "").strip()
    if not url:
        raise ValueError("stub listing requires url")
    title = (item.get("title") or "").strip() or "Licytacja komornicza"
    return normalized_listing(
        title=title,
        description=None,
        price_pln=None,
        location="Polska",
        city="Polska",
        source=source,
        source_url=url,
        auction_date=None,
        images=[],
        raw_data={"stub_from_list": True},
        region=item.get("region"),
    )


def _extract_city(location: str) -> str:
    """Heuristic: first comma-separated part or whole if short."""
    if not location:
        return "Polska"
    parts = [p.strip() for p in location.split(",")]
    return parts[0] if parts else location


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
    max_listings = scraping.get("max_listings")
    pw_delay = float(scraping.get("playwright_delay_seconds", 3.0))
    days_back = scraping.get("days_back")
    cutoff = _cutoff_for_days_back(int(days_back)) if days_back is not None else None

    results = []
    all_items: list[dict[str, str]] = []
    use_playwright = False

    with httpx.Client(headers=DEFAULT_HEADERS, timeout=60.0, follow_redirects=True) as client:
        try:
            resp = sync_get_with_retry(client, FILTER_NIERUCHOMOSCI, delay_seconds=delay)
            soup = BeautifulSoup(resp.text, "html.parser")
            first_page_items = _parse_list_page_from_soup(soup, BASE_URL)
            if first_page_items:
                all_items.extend(first_page_items)
                logger.info("Komornik list page 1 (httpx): {} links", len(first_page_items))
                for page in range(2, max_pages + 1):
                    list_url = f"{FILTER_NIERUCHOMOSCI}?page={page}"
                    resp = sync_get_with_retry(client, list_url, delay_seconds=delay)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_items = _parse_list_page_from_soup(soup, BASE_URL)
                    if not page_items:
                        break
                    all_items.extend(page_items)
                    logger.info("Komornik list page {} (httpx): {} links", page, len(page_items))
                    if max_listings is not None and len(all_items) >= max_listings:
                        break
            else:
                use_playwright = True
                logger.info("Komornik: list is JS-rendered, using Playwright")
        except Exception as e:
            logger.warning("Komornik httpx list failed: {}, trying Playwright", e)
            use_playwright = True

        if use_playwright:
            all_items = []
            for p in range(1, max_pages + 1):
                try:
                    page_items = asyncio.run(
                        _fetch_list_items_playwright(FILTER_NIERUCHOMOSCI, p, pw_delay)
                    )
                    if not page_items:
                        break
                    all_items.extend(page_items)
                    logger.info("Komornik list page {} (Playwright): {} links", p, len(page_items))
                    if max_listings is not None and len(all_items) >= max_listings:
                        break
                except Exception as e:
                    logger.warning("Komornik Playwright page {} failed: {}", p, e)
                    break

        to_fetch = all_items
        if max_listings is not None:
            to_fetch = all_items[:max_listings]

        if use_playwright:
            # Detail pages are also JS-rendered; fetch with Playwright.
            urls = [item["url"] for item in to_fetch]
            detail_htmls = asyncio.run(_fetch_detail_pages_playwright(urls, pw_delay))
            for item in to_fetch:
                html = detail_htmls.get(item["url"])
                row = None
                if html:
                    try:
                        row = _parse_detail_page(html, item["url"])
                    except Exception as e:
                        logger.warning("Parse listing {}: {} (saving stub)", item["url"][:60], e)
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
                                continue
                        except (ValueError, TypeError):
                            pass
                    results.append(row)
                else:
                    results.append(_stub_listing_from_item(item, "komornik"))
                if max_listings is not None and len(results) >= max_listings:
                    break
        else:
            for item in to_fetch:
                row = None
                try:
                    r = sync_get_with_retry(client, item["url"], delay_seconds=delay)
                    row = _parse_detail_page(r.text, item["url"])
                except Exception as e:
                    logger.warning("Fetch/parse listing {}: {} (saving stub)", item["url"][:60], e)
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
                                continue
                        except (ValueError, TypeError):
                            pass
                    results.append(row)
                else:
                    results.append(_stub_listing_from_item(item, "komornik"))
                if max_listings is not None and len(results) >= max_listings:
                    break
    return results
