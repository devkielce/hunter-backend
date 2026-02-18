"""Parse Polish price strings to integer grosze. Handles edge cases."""
from __future__ import annotations

import re
from typing import Optional

# Phrases that mean "no price" → return None
NO_PRICE_PHRASES = (
    "zapytaj o cenę",
    "zapytaj o cene",
    "cena do negocjacji",
    "cena do uzgodnienia",
    "na zapytanie",
    "do uzgodnienia",
    "kontakt",
)

# Match numbers with Polish formatting: 1 234,56 or 1234,56 or 1.234,56
_PRICE_RE = re.compile(
    r"(?:\d[\d\s.]*,\d{2}|\d[\d\s.]*)"
)


def _clean(s: str) -> str:
    return (s or "").strip().lower()


def _normalize_number(s: str) -> str:
    """Remove spaces and replace comma with dot."""
    s = s.replace(" ", "").replace("\xa0", "").replace(".", "").replace(",", ".")
    return s


def price_pln_from_text(text: Optional[str]) -> Optional[int]:
    """
    Parse Polish price string to PLN in grosze (integer).
    Returns None for empty, 'Zapytaj o cenę', 'Cena do negocjacji', etc.
    """
    if not text or not (t := _clean(text)):
        return None
    for phrase in NO_PRICE_PHRASES:
        if phrase in t:
            return None
    # Try to find a number (optionally with zł / PLN)
    match = _PRICE_RE.search(t)
    if not match:
        return None
    num_str = _normalize_number(match.group(0))
    try:
        value = float(num_str)
    except ValueError:
        return None
    # Assume PLN if no currency; if "eur" in text we could convert (not required here)
    pln = value
    if "eur" in t or "€" in t:
        # Optional: apply rate; for now treat as PLN equivalent placeholder or skip
        pass
    return int(round(pln * 100))  # grosze
