"""
Krótki tytuł oferty w jednym zdaniu (bez AI): np. "Mieszkanie 2-pokojowe, 45 m²", "Dom, 3 kondygnacje".
Ekstrakcja z opisu/tytułu: typ nieruchomości, liczba pokoi, metraż, kondygnacje.
"""
from __future__ import annotations

import re
from typing import Optional

# Typ nieruchomości – kolejność ma znaczenie (bardziej konkretne pierwsze)
_TYPE_PATTERNS = [
    (re.compile(r"\bkawalerka\b", re.I), "Kawalerka"),
    (re.compile(r"\blokal\s+u[żz]ytkowy\b", re.I), "Lokal użytkowy"),
    (re.compile(r"\bdom\s+(jednorodzinny|wolnostoj[ąa]cy|parterowy)\b", re.I), "Dom"),
    (re.compile(r"\bdom\b", re.I), "Dom"),
    (re.compile(r"\bdzia[łl]ka\b", re.I), "Działka"),
    (re.compile(r"\bmieszkanie\b", re.I), "Mieszkanie"),
    (re.compile(r"\bsegment\b", re.I), "Segment"),
    (re.compile(r"\bblok\b", re.I), "Mieszkanie"),  # w bloku → mieszkanie
]

# Liczba pokoi (dla mieszkania/kawalerki)
_ROOMS_RE = re.compile(
    r"(?:(\d+)\s*pok(?:oj[eiuó]|\.)|kawalerka)",
    re.I,
)
# Metraż: 45 m², 45 m2, 45,5 m², pow. 60, powierzchnia 60
_SURFACE_RE = re.compile(
    r"(?:(\d+[,.]?\d*)\s*m[²2]|pow\.?\s*(\d+[,.]?\d*)|powierzchnia\s*(\d+[,.]?\d*))",
    re.I,
)
# Kondygnacje / piętro
_FLOOR_RE = re.compile(
    r"(?:(\d+)\s*kondygnacj[ei]|\bparter\b|(?:na\s+)?(\d+)\s*pi[eę]tro)",
    re.I,
)

_MAX_TITLE_LEN = 120
_SURFACE_MIN, _SURFACE_MAX = 5, 5000  # sensowne m²
_ROOMS_MIN, _ROOMS_MAX = 1, 15


def _extract_type(text: str) -> Optional[str]:
    for pattern, label in _TYPE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _extract_rooms(text: str) -> Optional[int]:
    m = _ROOMS_RE.search(text)
    if not m:
        return None
    if m.group(0).lower().startswith("kawalerka"):
        return 1
    try:
        n = int(m.group(1))
        if _ROOMS_MIN <= n <= _ROOMS_MAX:
            return n
    except (TypeError, ValueError):
        pass
    return None


def _extract_surface(text: str) -> Optional[float]:
    m = _SURFACE_RE.search(text)
    if not m:
        return None
    for g in m.groups():
        if g is None:
            continue
        try:
            val = float(g.replace(",", "."))
            if _SURFACE_MIN <= val <= _SURFACE_MAX:
                return val
        except ValueError:
            continue
    return None


def _extract_floor(text: str) -> Optional[str]:
    """Zwraca np. '3 kondygnacje', 'parter', '1 piętro'."""
    m = _FLOOR_RE.search(text)
    if not m:
        return None
    s = m.group(0).strip()
    if "parter" in s.lower():
        return "parter"
    if "kondygnacj" in s.lower():
        return s  # np. "3 kondygnacje"
    if "piętro" in s.lower() or "pietro" in s.lower():
        return s  # np. "1 piętro"
    return None


def _first_line_or_sentence(text: str, max_len: int = 100) -> str:
    """Pierwsza linia lub pierwsze zdanie (do kropki) z text."""
    if not text or not text.strip():
        return ""
    t = text.strip()
    for sep in ("\n", ". ", ".\n"):
        idx = t.find(sep)
        if idx != -1:
            t = t[: idx + (1 if sep == "\n" else 2)].strip()
            if t.endswith("."):
                t = t[:-1]
            break
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip()
        if t and not t[-1].isspace():
            t = t + "…"
    return t


def extract_short_title(text: Optional[str], fallback: Optional[str] = None) -> str:
    """
    Z tekstu (opis + tytuł) wyciąga krótki tytuł w jednym zdaniu, np.:
    "Mieszkanie 2-pokojowe, 45 m²", "Dom, 3 kondygnacje", "Kawalerka, 28 m²", "Działka, 500 m²".

    Gdy nic nie uda się wyciągnąć, zwraca fallback lub pierwszą linię/zdanie z text (max ~100 znaków).
    """
    if not text or not text.strip():
        return (fallback or "").strip() or "Oferta"

    t = " " + text.strip().replace("\n", " ") + " "
    prop_type = _extract_type(t)
    rooms = _extract_rooms(t)
    surface = _extract_surface(t)
    floor = _extract_floor(t)

    parts = []

    if prop_type:
        parts.append(prop_type)
        if prop_type in ("Mieszkanie", "Segment") and rooms is not None:
            parts.append(f"{rooms}-pokojowe")
        if surface is not None:
            s_str = str(int(surface)) if surface == int(surface) else f"{surface:.1f}".replace(".", ",")
            parts.append(f"{s_str} m²")
        if floor and prop_type == "Dom":
            parts.append(floor)
        elif floor and not surface and prop_type in ("Mieszkanie", "Kawalerka"):
            parts.append(floor)
    elif surface is not None:
        s_str = str(int(surface)) if surface == int(surface) else f"{surface:.1f}".replace(".", ",")
        parts.append(f"Mieszkanie, {s_str} m²")

    if parts:
        title = ", ".join(parts)
        if len(title) > _MAX_TITLE_LEN:
            title = title[:_MAX_TITLE_LEN - 1].rstrip()
            if not title.endswith("²") and not title.endswith(","):
                title = title + "…"
        return title

    if fallback and fallback.strip():
        return fallback.strip()[:_MAX_TITLE_LEN]
    return _first_line_or_sentence(text, _MAX_TITLE_LEN) or "Oferta"
