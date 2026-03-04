"""Tests for Facebook (Apify) real-estate filter: only nieruchomości from mixed group posts."""
from __future__ import annotations

import pytest

from hunter.apify_facebook import (
    _parse_post_date,
    passes_real_estate_filter,
    normalize_facebook_item,
)


def test_passes_real_estate_filter_accepts_mieszkanie():
    assert passes_real_estate_filter("Sprzedam mieszkanie 3 pokoje, 65 m², 450 000 zł") is True


def test_passes_real_estate_filter_accepts_wynajem():
    assert passes_real_estate_filter("Wynajmę lokal użytkowy w centrum, czynsz 3000 zł") is True


def test_passes_real_estate_filter_accepts_dzialka():
    assert passes_real_estate_filter("Działka budowlana 500 m2, ul. Leśna") is True


def test_passes_real_estate_filter_rejects_skuter():
    assert passes_real_estate_filter("Sprzedam skuter 50cc, stan dobry, cena 2000 zł") is False


def test_passes_real_estate_filter_rejects_bizuteria():
    assert passes_real_estate_filter("Biżuteria srebrna, naszyjnik, 150 zł") is False


def test_passes_real_estate_filter_rejects_empty():
    assert passes_real_estate_filter("") is False
    assert passes_real_estate_filter("   ") is False


def test_normalize_facebook_item_filters_out_non_real_estate():
    item = {
        "postUrl": "https://facebook.com/groups/xyz/posts/123",
        "text": "Sprzedam rower górski, cena 800 zł, tel. 500...",
    }
    assert normalize_facebook_item(item) is None


def test_normalize_facebook_item_keeps_real_estate():
    item = {
        "postUrl": "https://facebook.com/groups/xyz/posts/456",
        "text": "Wynajmę mieszkanie 2 pokoje, 45 m², 2500 zł + media",
    }
    row = normalize_facebook_item(item)
    assert row is not None
    assert row.get("source") == "facebook"
    assert row.get("source_url") == "https://facebook.com/groups/xyz/posts/456"


def test_parse_post_date_iso():
    item = {"date_posted": "2024-06-15T10:00:00.000Z"}
    dt = _parse_post_date(item)
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 6
    assert dt.day == 15


def test_parse_post_date_timestamp():
    # 2024-01-01 12:00:00 UTC
    item = {"timestamp": 1704110400}
    dt = _parse_post_date(item)
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1


def test_normalize_facebook_item_sets_auction_date_when_in_item():
    item = {
        "postUrl": "https://facebook.com/groups/xyz/posts/789",
        "text": "Wynajmę mieszkanie 2 pokoje, 45 m²",
        "date_posted": "2024-05-20T08:00:00Z",
    }
    row = normalize_facebook_item(item)
    assert row is not None
    assert row.get("auction_date") is not None
    assert "2024-05-20" in row["auction_date"]
