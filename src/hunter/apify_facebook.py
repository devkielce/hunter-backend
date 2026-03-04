"""
Apify → Facebook posts: fetch dataset by ID, filter to real estate only, normalize to listings, upsert to Supabase.
Webhook receives datasetId (or resource.id); we GET dataset items, filter (only nieruchomości), normalize, upsert.
When price is missing in post text, optionally follow first "offer" link (e.g. arcabinvestments.com) to extract price.

Filtr „tylko nieruchomości” stosowany jest wyłącznie do Facebooka (grupy mieszane: skutery, biżuteria itd.).
E-licytacje i AMW nie używają tego filtra – tam treść to z założenia oferty nieruchomości.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

# Pola z datą posta w odpowiedzi Apify (różne aktory)
_POST_DATE_KEYS = ("date_posted", "postedAt", "time", "created_time", "timestamp")

import httpx
from loguru import logger

from hunter.config import get_config
from hunter.http_utils import DEFAULT_HEADERS
from hunter.price_fallback import extract_first_offer_url, fetch_price_from_url
from hunter.price_parser import price_pln_from_full_text
from hunter.schema import for_supabase, normalized_listing
from hunter.supabase_client import (
    archive_listings_older_than,
    get_client,
    log_scrape_run,
    upsert_listings,
)
from hunter.investment_score import compute_investment_score, compute_medians_per_region
from hunter.title_extractor import extract_short_title

# Słowa charakterystyczne dla nieruchomości – post musi zawierać co najmniej jedno (Facebook: tylko takie trafiają do listings)
REAL_ESTATE_KEYWORDS = [
    "nieruchomość",
    "nieruchomosc",
    "mieszkanie",
    "dom",
    "działka",
    "dzialka",
    "lokal",
    "wynajem",
    "do wynajęcia",
    "do wynajecia",
    "wynajmę",
    "wynajme",
    "sprzedaż mieszkania",
    "sprzedaz mieszkania",
    "sprzedam mieszkanie",
    "sprzedam dom",
    "pokoje",
    "kawalerka",
    "metraż",
    "metraz",
    "m²",
    "m2",
    "powierzchnia",
    "blok",
    "osiedle",
    "czynsz",
    "na sprzedaż",
    "ul. ",
    "ul ",
]

# Słowa wykluczające – post z tymi słowami (jako główny temat) nie jest nieruchomością; pomijamy
NON_REAL_ESTATE_KEYWORDS = [
    "skuter",
    "motor",
    "motocykl",
    "biżuteria",
    "bizuteria",
    "rower",
    "samochód",
    "samochod",
    "auto ",
    "meble",
    "odzież",
    "odziez",
    "telefon",
    "laptop",
    "komputer",
    "zwierzę",
    "zwierze",
    "pies ",
    "kot ",
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


def passes_real_estate_filter(text: str) -> bool:
    """
    True tylko jeśli post wygląda na ofertę nieruchomości (Facebook groups: odfiltrowanie skuterów, biżuterii itd.).
    Wymaga: co najmniej jedno słowo z REAL_ESTATE_KEYWORDS.
    Odrzuca: posty zawierające słowa z NON_REAL_ESTATE_KEYWORDS (główny temat to nie nieruchomość).
    """
    if not text or not text.strip():
        return False
    t = text.lower()
    if any(kw.lower() in t for kw in NON_REAL_ESTATE_KEYWORDS):
        return False
    return any(kw.lower() in t for kw in REAL_ESTATE_KEYWORDS)


def _parse_post_date(item: dict[str, Any]) -> Optional[datetime]:
    """Wyciąga datę posta z itemu Apify (date_posted, postedAt, time, created_time, timestamp). Zwraca datetime UTC lub None."""
    for key in _POST_DATE_KEYS:
        val = item.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            try:
                ts = float(val)
                if ts > 1e12:  # milliseconds
                    ts = ts / 1000.0
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError):
                continue
        if isinstance(val, str) and val.strip():
            s = val.strip()
            try:
                if "T" in s:
                    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    return None


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


def normalize_facebook_item(
    item: dict[str, Any],
    config: Optional[dict] = None,
) -> Optional[dict[str, Any]]:
    """
    Jedna wpis z datasetu Apify (Facebook) → znormalizowany listing lub None.
    source_url jest wymagany; jeśli brak – pomijamy.
    Gdy w tekście brak ceny, próbuje wyciągnąć cenę z pierwszego linku do oferty (np. arcabinvestments.com).
    """
    source_url = _source_url_from_item(item)
    if not source_url:
        return None
    text = _text_from_item(item)
    if not passes_real_estate_filter(text):
        return None
    fallback_title = (text[:500] + "…") if len(text) > 500 else (text or "Post Facebook")
    title = extract_short_title(text, fallback=fallback_title)
    images = _images_from_item(item)

    price_pln = price_pln_from_full_text(text)
    raw_extra = {}
    if price_pln is None:
        cfg = config or get_config()
        scraping = (cfg.get("scraping") or {})
        follow = scraping.get("follow_link_for_price", True)
        if follow:
            allowed = scraping.get("follow_link_domains")
            if isinstance(allowed, list):
                allowed = [str(d).strip().lower() for d in allowed if d]
            offer_url = extract_first_offer_url(text, allowed_domains=allowed)
            if offer_url:
                delay = float(scraping.get("httpx_delay_seconds", 1.5))
                with httpx.Client(headers=DEFAULT_HEADERS, timeout=10.0, follow_redirects=True) as client:
                    price_pln = fetch_price_from_url(offer_url, client, delay=delay, timeout=10.0)
                if price_pln is not None:
                    raw_extra["price_from_followed_link"] = True
                    raw_extra["followed_price_url"] = offer_url

    raw_data = {k: v for k, v in item.items() if k not in ("images", "image")}
    raw_data.update(raw_extra)
    auction_date = _parse_post_date(item)
    return normalized_listing(
        title=title,
        description=text[:5000] if text else None,
        price_pln=price_pln,
        location="",
        city="",
        source="facebook",
        source_url=source_url,
        auction_date=auction_date,
        images=images,
        raw_data=raw_data,
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
    logger.info("Apify Facebook: fetched {} raw items for dataset_id={}", len(raw_items), dataset_id)
    rows_raw = []
    for item in raw_items:
        try:
            row = normalize_facebook_item(item, config=cfg)
            if row:
                rows_raw.append(row)
        except Exception as e:
            logger.warning("Skip Facebook item: {}", e)
    if not rows_raw:
        logger.info("Apify Facebook: 0 listings after filter (dataset_id={})", dataset_id)
        return 0, 0
    medians = compute_medians_per_region(rows_raw)
    for r in rows_raw:
        r.setdefault("raw_data", {})
        score = compute_investment_score(r, medians, cfg)
        r["raw_data"]["investment_score"] = score
    rows = [for_supabase(r) for r in rows_raw]
    client = get_client()
    finished_at = datetime.now(timezone.utc).isoformat()
    started_at = finished_at
    for row in rows:
        row["last_seen_at"] = finished_at
    upserted = upsert_listings(client, rows)
    log_scrape_run(
        client,
        "facebook",
        started_at,
        finished_at,
        len(rows_raw),
        upserted,
        "success",
        None,
    )
    months = (cfg.get("scraping") or {}).get("archive_older_than_months", 2)
    archive_listings_older_than(client, "facebook", interval=f"{months} months")
    return len(rows_raw), upserted
