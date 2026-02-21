"""Tests for AMW scraper: detail URL extraction and hash fallback."""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from hunter.scrapers.amw import (
    BASE_URL,
    _find_detail_url_in_card,
    _parse_list_page,
    scrape_amw,
)


# Minimal list-page card with a real detail link (h2 wrapped in <a>)
HTML_WITH_DETAIL_LINK = """
<div class="results">
  <a href="/pl/nieruchomosci/nieruchomosci-amw/oswiecim-ul-zwirki-i-wigury-25-3344">
    <h2>Oświęcim, ul. Żwirki i Wigury 25, lok U1</h2>
  </a>
  <p>Powierzchnia 54,51 m2</p>
  <p>Cena wywoławcza 900 PLN</p>
  <p>Woj.: małopolskie</p>
  <p>W dniu: 05.03.2026r, godz. 12:00</p>
</div>
"""

# Card with no detail link (only search/sort links)
HTML_WITHOUT_DETAIL_LINK = """
<div class="results">
  <h2>Brzeg, ul. Chrobrego 14F,</h2>
  <p>Woj.: opolskie</p>
  <p>Cena wywoławcza 100 000 PLN</p>
  <a href="/pl/nieruchomosci/nieruchomosci-amw/wyniki-wyszukiwania/search,,page,0">Szukaj</a>
</div>
"""

# Card with detail link inside sibling (not wrapping h2)
HTML_DETAIL_IN_SIBLING = """
<div class="results">
  <h2>Bielsko-Biała, ul. Piotra Bardowskiego 12, lok. U002</h2>
  <p>Powierzchnia 116,17 m2</p>
  <p>Cena wywoławcza 2200 PLN</p>
  <p>Woj.: śląskie</p>
  <p><a href="/pl/nieruchomosci/nieruchomosci-amw/bielsko-biala-ul-bardowskiego-12-3355">Szczegóły oferty</a></p>
</div>
"""


def test_find_detail_url_in_card_when_h2_wrapped_in_a():
    """When the title h2 is wrapped in <a href=".../slug"> we get that path."""
    soup = BeautifulSoup(HTML_WITH_DETAIL_LINK, "html.parser")
    h2 = soup.select_one("h2")
    assert h2 is not None
    path = _find_detail_url_in_card(h2)
    assert path == "/pl/nieruchomosci/nieruchomosci-amw/oswiecim-ul-zwirki-i-wigury-25-3344"


def test_find_detail_url_in_card_when_link_in_sibling():
    """When the detail link is in a sibling element we still find it."""
    soup = BeautifulSoup(HTML_DETAIL_IN_SIBLING, "html.parser")
    h2 = soup.select_one("h2")
    assert h2 is not None
    path = _find_detail_url_in_card(h2)
    assert path == "/pl/nieruchomosci/nieruchomosci-amw/bielsko-biala-ul-bardowskiego-12-3355"


def test_find_detail_url_in_card_returns_none_when_no_detail_link():
    """When the card has no detail link we get None."""
    soup = BeautifulSoup(HTML_WITHOUT_DETAIL_LINK, "html.parser")
    h2 = soup.select_one("h2")
    assert h2 is not None
    path = _find_detail_url_in_card(h2)
    assert path is None


def test_parse_list_page_uses_real_detail_url():
    """When the list HTML has a detail link in a card, source_url is the full offer URL (no hash)."""
    soup = BeautifulSoup(HTML_WITH_DETAIL_LINK, "html.parser")
    items = _parse_list_page(soup, BASE_URL)
    assert len(items) == 1
    source_url = items[0]["source_url"]
    assert "oswiecim-ul-zwirki-i-wigury-25-3344" in source_url
    assert "#" not in source_url
    assert source_url.startswith(BASE_URL)


def test_parse_list_page_fallback_to_hash_when_no_detail_link():
    """When the card has no detail link, source_url is the hash-based fallback."""
    soup = BeautifulSoup(HTML_WITHOUT_DETAIL_LINK, "html.parser")
    items = _parse_list_page(soup, BASE_URL)
    assert len(items) == 1
    source_url = items[0]["source_url"]
    assert "/nieruchomosci-amw/#" in source_url
    assert len(source_url) > len(BASE_URL) + 30


def test_scrape_amw_returns_listings_with_source_url():
    """Scrape returns list of dicts; at least one listing has source_url set (integration-style)."""
    # Run with minimal config to avoid many requests
    result = scrape_amw(config={"scraping": {"max_pages_auctions": 1, "httpx_delay_seconds": 0.5}})
    assert isinstance(result, list)
    for row in result:
        assert "source_url" in row
        assert row["source_url"]
        assert row.get("source") == "amw"
    # If the live list page includes detail links, we expect at least one real URL (no hash)
    real_urls = [r["source_url"] for r in result if "#" not in r["source_url"]]
    # We don't require real_urls to be non-empty so the test doesn't fail if AMW changes HTML
    assert len(result) >= 1, "scraper should return at least one listing from first page"
