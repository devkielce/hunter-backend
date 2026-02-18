"""Otodom.pl — Playwright async. Prefer __NEXT_DATA__ JSON when available."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional
from urllib.parse import urljoin

from loguru import logger

from hunter.price_parser import price_pln_from_text
from hunter.schema import normalized_listing


async def _fetch_listing_urls_playwright(base_url: str, max_pages: int, delay_seconds: float) -> list[str]:
    from playwright.async_api import async_playwright
    urls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            for page_num in range(1, max_pages + 1):
                url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(delay_seconds)
                # Otodom often has data in __NEXT_DATA__ or links like /pl/oferty/...
                link_handles = await page.query_selector_all("a[href*='/pl/oferty/'], a[href*='/oferta/']")
                for h in link_handles:
                    href = await h.get_attribute("href")
                    if href and "/oferty/" in href:
                        full = urljoin("https://www.otodom.pl", href)
                        if full not in urls:
                            urls.append(full)
                if not link_handles:
                    break
        finally:
            await browser.close()
    return urls


def _extract_next_data(html: str) -> Optional[dict]:
    """Extract __NEXT_DATA__ script JSON."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _listing_from_next_data(data: dict, source_url: str) -> Optional[dict[str, Any]]:
    """Build normalized listing from Otodom __NEXT_DATA__ (listing page)."""
    try:
        props = data.get("props", {}).get("pageProps", {}) or {}
        listing = props.get("listing", {}) or props.get("data", {}) or {}
        title = listing.get("title") or listing.get("name") or "Oferta Otodom"
        description = listing.get("description") or listing.get("descriptionPlain")
        if isinstance(description, dict):
            description = description.get("pl") or description.get("en") or ""
        price_raw = listing.get("price") or listing.get("totalPrice")
        if isinstance(price_raw, dict):
            price_raw = price_raw.get("value") or price_raw.get("amount")
        price_pln = price_pln_from_text(str(price_raw)) if price_raw is not None else None
        location = listing.get("location", {}) or {}
        if isinstance(location, dict):
            address = location.get("address", {}) or {}
            city = (address.get("city") or location.get("city") or "").strip() or "Polska"
            region = (address.get("region") or location.get("region") or "").strip()
            location_str = ", ".join(filter(None, [city, region]))
        else:
            location_str = str(location)
            city = location_str.split(",")[0].strip() if location_str else "Polska"
        images = list(listing.get("images", []) or [])
        if isinstance(images and images[0], dict):
            images = [img.get("url") or img.get("src") for img in images if img.get("url") or img.get("src")]
        return normalized_listing(
            title=title,
            description=description,
            price_pln=price_pln,
            location=location_str or "Polska",
            city=city,
            source="otodom",
            source_url=source_url,
            auction_date=None,
            images=images,
            raw_data={"listing": listing, "url": source_url},
        )
    except Exception as e:
        logger.warning("Otodom __NEXT_DATA__ parse error: {}", e)
        return None


async def _scrape_otodom_async(config: Optional[dict] = None) -> list[dict[str, Any]]:
    cfg = config or {}
    scraping = cfg.get("scraping", {})
    delay = float(scraping.get("playwright_delay_seconds", 4))
    max_pages = int(scraping.get("max_pages_classifieds", 10))

    base_url = "https://www.otodom.pl/pl/nieruchomosci/sprzedaz"
    from playwright.async_api import async_playwright

    listing_urls = await _fetch_listing_urls_playwright(base_url, max_pages, delay)
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for url in listing_urls:
                try:
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(delay)
                    html = await page.content()
                    await page.close()
                    data = _extract_next_data(html)
                    if data:
                        row = _listing_from_next_data(data, url)
                        if row:
                            results.append(row)
                    else:
                        # Fallback: minimal from HTML if no __NEXT_DATA__
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, "html.parser")
                        title_el = soup.select_one("h1, [data-cy='adPageAdTitle']")
                        title = title_el.get_text(strip=True) if title_el else "Oferta Otodom"
                        desc_el = soup.select_one("[data-cy='adPageAdDescription']")
                        desc = desc_el.get_text(strip=True)[:5000] if desc_el else None
                        price_el = soup.select_one("[data-cy='adPageHeaderPrice']")
                        price_pln = price_pln_from_text(price_el.get_text(strip=True) if price_el else None)
                        loc_el = soup.select_one("[data-cy='adPageHeaderLocation']")
                        loc = loc_el.get_text(strip=True) if loc_el else "Polska"
                        city = loc.split(",")[0].strip() if loc else "Polska"
                        results.append(normalized_listing(
                            title=title,
                            description=desc,
                            price_pln=price_pln,
                            location=loc,
                            city=city,
                            source="otodom",
                            source_url=url,
                            auction_date=None,
                            images=[],
                            raw_data={"url": url},
                        ))
                except Exception as e:
                    logger.warning("Skip Otodom listing {}: {}", url, e)
        finally:
            await browser.close()
    return results


def scrape_otodom(config: Optional[dict] = None) -> list[dict[str, Any]]:
    """Synchronous entry: run async scraper."""
    return asyncio.run(_scrape_otodom_async(config))
