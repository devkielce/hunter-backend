"""Shared helpers for scrapers (error-page detection, etc.)."""
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
