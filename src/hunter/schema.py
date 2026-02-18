"""Unified normalized schema for all sources."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

SOURCE_LITERAL = Literal["komornik", "e_licytacje", "olx", "otodom", "gratka", "facebook"]


def normalized_listing(
    *,
    title: str,
    description: Optional[str],
    price_pln: Optional[int],
    location: str,
    city: str,
    source: SOURCE_LITERAL,
    source_url: str,
    auction_date: Optional[datetime] = None,
    images: Optional[list[str]] = None,
    raw_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a normalized listing dict. price_pln in grosze."""
    return {
        "title": title,
        "description": description or None,
        "price_pln": price_pln,
        "location": location,
        "city": city,
        "source": source,
        "source_url": source_url,
        "auction_date": auction_date.isoformat() if auction_date else None,
        "images": images or [],
        "raw_data": raw_data or {},
    }


def for_supabase(row: dict[str, Any]) -> dict[str, Any]:
    """Prepare row for Supabase upsert (e.g. ensure JSON-serializable)."""
    out = dict(row)
    if "auction_date" in out and out["auction_date"] and hasattr(out["auction_date"], "isoformat"):
        out["auction_date"] = out["auction_date"].isoformat()
    return out
