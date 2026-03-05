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
    "cena do ustalenia",
    "do ustalenia",
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


# Patterns to find price in long text (e.g. "cena wywołania wynosi 61 500,00 zł", "Cena wywoławcza 132 000,00 PLN" on AMW)
# Use \s* only (no [\d\s]*) so we don't consume digits of the price.
_PRICE_IN_TEXT_PATTERNS = [
    re.compile(
        r"cena\s+wywo[łl]awcza\s+(\d[\d\s.,]*)\s*PLN",
        re.I,
    ),  # AMW: "Cena wywoławcza 132 000,00 PLN"
    re.compile(
        r"cena\s+wywo[łl]ania\s+(?:jest\s+równa\s+|wynosi\s+)\s*(\d[\d\s.,]*)\s*z[łl]",
        re.I,
    ),
    re.compile(
        r"suma\s+oszacowania\s+wynosi\s+(\d[\d\s.,]*)\s*z[łl]",
        re.I,
    ),
    re.compile(
        r"(?:wynosi|równa)\s+(\d[\d\s.,]+)\s*z[łl]",
        re.I,
    ),
    re.compile(
        r"czynsz\s+(?:netto|brutto)?\s*[:\s]*(\d[\d\s.,]*)\s*z[łl]",
        re.I,
    ),
    re.compile(
        r"(\d[\d\s]{2,}(?:,\d{2})?)\s*PLN\b",
        re.I,
    ),  # e.g. "132 000,00 PLN" (AMW and others)
    re.compile(
        r"(\d[\d\s]{2,}(?:,\d{2})?)\s*z[łl]\b",
        re.I,
    ),  # e.g. "61 500,00 zł" or "6 000 zł"
]


def price_pln_from_full_text(text: Optional[str]) -> Optional[int]:
    """
    Search long text for price patterns (e.g. obwieszczenie komornicze, opis AMW).
    Returns first valid price found as grosze, or None.
    """
    if not text or not text.strip():
        return None
    for pat in _PRICE_IN_TEXT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        snippet = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
        parsed = price_pln_from_text(snippet)
        if parsed is not None:
            return parsed
    return None
