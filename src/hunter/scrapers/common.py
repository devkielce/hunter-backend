"""Shared helpers for scrapers (error-page detection, sale vs rent, etc.)."""
from __future__ import annotations

from typing import Optional

# Phrases that indicate an error/maintenance page, not a real listing. Case-insensitive match.
ERROR_PAGE_PHRASES = (
    "brak połączenia z internetem",
    "no internet connection",
    "błąd",
    "error",
    "strona tymczasowo niedostępna",
    "maintenance",
    "przerwa techniczna",
)


def is_likely_error_page(title: Optional[str], description: Optional[str] = None) -> bool:
    """
    True if title or description looks like an error/maintenance page, not a real listing.
    Use before returning a listing from a detail parser, or before upserting to DB.
    """
    text = " ".join(
        part for part in (title or "", description or "") if part and isinstance(part, str)
    ).strip()
    if not text:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in ERROR_PAGE_PHRASES)


# Sale-only filter: exclude listings that are clearly for rent (wynajem), keep sale/auction.
RENTAL_PHRASES = (
    "na wynajem",
    "do wynajęcia",
    "do wynajecia",
    "wynajmę",
    "wynajme",
    "wynajem ",
    " wynajem",
    "wynajem.",
    "wynajem,",
    "wynajmu",
    "do wynajmu",
)
SALE_OR_AUCTION_PHRASES = (
    "sprzedaż",
    "sprzedaz",
    "na sprzedaż",
    "na sprzedaz",
    "sprzedam",
    "sprzedaj",
    "licytacja",
    "licytacj",
    "cena wywoławcza",
    "cena wywolawcza",
    "wywołania",
    "wywolania",
    "aukcja",
    "aukcji",
)


def is_rental_only(title: Optional[str], description: Optional[str]) -> bool:
    """
    True if the listing looks like rent-only (wynajem), not sale/auction.
    Used to filter out rental listings so we keep only "na sprzedaż" / auction.
    If text has rental phrases and no sale/auction phrases → treat as rental-only (exclude).
    Komornik/e-licytacje/AMW are typically auction/sale; Facebook/others may have both.
    """
    text = " ".join(
        part for part in (title or "", description or "") if part and isinstance(part, str)
    ).strip()
    if not text:
        return False
    lower = text.lower()
    has_rental = any(p.lower() in lower for p in RENTAL_PHRASES)
    has_sale = any(p.lower() in lower for p in SALE_OR_AUCTION_PHRASES)
    return bool(has_rental and not has_sale)
