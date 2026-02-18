"""
Apify → Facebook posts: fetch dataset by ID, filter by sales keywords, normalize to listings, upsert to Supabase.
Webhook receives datasetId (or resource.id); we GET dataset items, filter, normalize, upsert.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from loguru import logger

from hunter.config import get_config
from hunter.schema import for_supabase, normalized_listing
from hunter.supabase_client import get_client, log_scrape_run, upsert_listings

# Słowa sprzedażowe – tylko itemy zawierające co najmniej jedno trafiają do listings
SALES_KEYWORDS = [
    "sprzedaż",
    "sprzedam",
    "sprzedaję",
    "cena",
    "zł",
    "zl",
    "nieruchomość",
    "nieruchomosc",
    "mieszkanie",
    "dom",
    "działka",
    "dzialka",
    "licytacja",
    "wynajem",
    "do wynajęcia",
    "do wynajecia",
]

APIFY_DATASET_ITEMS_URL = "https://api.apify.com/v2/datasets/{dataset_id}/items"


def _get_apify_token(config: Optional[dict] = None) -> str:
    cfg = config or get_config()
    token = (cfg.get("apify", {}) or {}).get("token") or ""
    if not token:
        raise ValueError("apify.token or APIFY_TOKEN required for Apify integration")
    return token.strip()


def _text_from_item(item: dict[str, Any]) -> str:
    """Sklej tekst z posta z dostępnych pól."""
    parts = []
    for key in ("title", "text", "message", "content", "description"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return " ".join(parts) if parts else ""


def passes_sales_filter(text: str) -> bool:
    """True jeśli tekst zawiera przynajmniej jedno słowo sprzedażowe (case-insensitive)."""
    if not text:
        return False
    t = text.lower()
    return any(kw.lower() in t for kw in SALES_KEYWORDS)


def _source_url_from_item(item: dict[str, Any]) -> Optional[str]:
    url = item.get("postUrl") or item.get("url") or item.get("link") or item.get("post_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def _images_from_item(item: dict[str, Any]) -> list[str]:
    urls = []
    images = item.get("images") or item.get("image")
    if isinstance(images, list):
        for x in images:
            if isinstance(x, str) and x.strip():
                urls.append(x.strip())
            elif isinstance(x, dict) and (x.get("url") or x.get("src")):
                u = x.get("url") or x.get("src")
                if isinstance(u, str):
                    urls.append(u.strip())
    elif isinstance(images, str) and images.strip():
        urls.append(images.strip())
    return urls


def normalize_facebook_item(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Jedna wpis z datasetu Apify (Facebook) → znormalizowany listing lub None.
    source_url jest wymagany; jeśli brak – pomijamy.
    """
    source_url = _source_url_from_item(item)
    if not source_url:
        return None
    text = _text_from_item(item)
    if not passes_sales_filter(text):
        return None
    title = (text[:500] + "…") if len(text) > 500 else (text or "Post Facebook")
    images = _images_from_item(item)
    return normalized_listing(
        title=title,
        description=text[:5000] if text else None,
        price_pln=None,
        location="",
        city="",
        source="facebook",
        source_url=source_url,
        auction_date=None,
        images=images,
        raw_data={k: v for k, v in item.items() if k not in ("images", "image")},
    )


def fetch_dataset_items(dataset_id: str, token: str) -> list[dict[str, Any]]:
    """Pobierz wszystkie itemy z datasetu Apify."""
    url = APIFY_DATASET_ITEMS_URL.format(dataset_id=dataset_id).rstrip("/")
    # Token w query (Apify accepts token as query param)
    full_url = f"{url}?token={token}"
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(full_url)
        resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return data


def process_apify_dataset(
    dataset_id: str,
    config: Optional[dict] = None,
) -> tuple[int, int]:
    """
    Pobierz dataset z Apify, przefiltruj i znormalizuj, upsert do Supabase.
    Zwraca (listings_found, listings_upserted).
    """
    cfg = config or get_config()
    token = _get_apify_token(cfg)
    raw_items = fetch_dataset_items(dataset_id, token)
    rows = []
    for item in raw_items:
        try:
            row = normalize_facebook_item(item)
            if row:
                rows.append(for_supabase(row))
        except Exception as e:
            logger.warning("Skip Facebook item: {}", e)
    if not rows:
        logger.info("Apify Facebook: 0 listings after filter (dataset_id={})", dataset_id)
        return 0, 0
    client = get_client()
    upserted = upsert_listings(client, rows)
    started_at = datetime.now(timezone.utc).isoformat()
    finished_at = datetime.now(timezone.utc).isoformat()
    log_scrape_run(
        client,
        "facebook",
        started_at,
        finished_at,
        len(rows),
        upserted,
        "success",
        None,
    )
    return len(rows), upserted
