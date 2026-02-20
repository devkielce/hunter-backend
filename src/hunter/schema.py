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
    region: Optional[str] = None,
) -> dict[str, Any]:
    """Build a normalized listing dict. price_pln in grosze. region = województwo for frontend filtering."""
    # Never store empty string for dates: use None so frontend ?? fallback works
    auction_date = auction_date or None
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
        "region": region,
    }


def for_supabase(row: dict[str, Any]) -> dict[str, Any]:
    """Prepare row for Supabase upsert (e.g. ensure JSON-serializable)."""
    out = dict(row)
    if "auction_date" in out:
        val = out["auction_date"]
        if val is None or (isinstance(val, str) and not val.strip()):
            out["auction_date"] = None
        elif hasattr(val, "isoformat"):
            out["auction_date"] = val.isoformat()
    # else already a string (e.g. from normalized_listing); leave as is
    return out
