"""
Investment score (0–100) dla ofert: potencjał inwestycyjny na podstawie ceny za m², yield, lokacji, ryzyka.
MVP: bez AI, bez zewnętrznych API. Szczegóły: docs/SCORING_HUNTER.md.
"""
from __future__ import annotations

import re
import statistics
from typing import Any, Optional

from hunter.title_extractor import extract_surface_m2

# Czynsz: "czynsz 2500 zł", "2500 zł/mies", "2500 zł miesięcznie"
_RENT_RE = re.compile(
    r"(?:czynsz|zł/mies|zł\s*miesięcznie|miesięcznie)\s*[:\s]*(\d[\d\s]*)\s*zł|(\d[\d\s]+)\s*zł\s*(?:/mies|miesięcznie)",
    re.I,
)
# Ryzyko: słowa w opisie
_RISK_WORDS = re.compile(r"\b(spór|spor|zajęcie|zajecie|obciążenie|obciazenie)\b", re.I)

_DEFAULT_WEIGHTS = {
    "price_anomaly": 0.35,
    "yield": 0.25,
    "location": 0.25,
    "risk": 0.15,
}
_DEFAULT_RISK_BY_SOURCE = {
    "komornik": 0.7,
    "e_licytacje": 0.5,
    "amw": 0.4,
    "facebook": 0.4,
}
_DEFAULT_LOCATION_SCORE = 0.5
_DEFAULT_MEDIAN_PRICE_M2 = 8000.0  # PLN/m² fallback


def get_surface_m2(listing: dict[str, Any]) -> Optional[float]:
    """Metraż z raw_data.surface_m2 lub ekstrakcja z description."""
    raw = listing.get("raw_data") or {}
    if isinstance(raw.get("surface_m2"), (int, float)):
        val = float(raw["surface_m2"])
        if 5 <= val <= 5000:
            return val
    desc = listing.get("description") or ""
    title = listing.get("title") or ""
    return extract_surface_m2(f"{title} {desc}")


def extract_rent_pln_per_month(description: Optional[str]) -> Optional[int]:
    """Czynsz miesięczny w PLN z opisu (do yield)."""
    if not description or not description.strip():
        return None
    m = _RENT_RE.search(description)
    if not m:
        return None
    for g in m.groups():
        if g is None:
            continue
        try:
            s = g.replace(" ", "").strip()
            if s:
                return int(s)
        except ValueError:
            continue
    return None


def compute_medians_per_region(listings: list[dict[str, Any]]) -> dict[str, float]:
    """
    Mediana ceny za m² per region z listy ofert (tylko te z price_pln i surface_m2).
    Klucz: region lub city lub 'default'.
    """
    by_region: dict[str, list[float]] = {}
    for row in listings:
        price = row.get("price_pln")
        if price is None or not isinstance(price, (int, float)) or price <= 0:
            continue
        surface = get_surface_m2(row)
        if surface is None or surface <= 0:
            continue
        price_per_m2 = (float(price) / 100.0) / surface
        if price_per_m2 <= 0 or price_per_m2 > 1e7:
            continue
        region = (row.get("region") or row.get("city") or "default")
        if isinstance(region, str):
            region = region.strip() or "default"
        else:
            region = "default"
        by_region.setdefault(region, []).append(price_per_m2)
    out = {}
    for region, values in by_region.items():
        if len(values) >= 1:
            out[region] = statistics.median(values)
    return out


def compute_investment_score(
    listing: dict[str, Any],
    median_by_region: dict[str, float],
    config: Optional[dict] = None,
) -> Optional[float]:
    """
    Score 0–100 (potencjał inwestycyjny). Gdy brak price_pln zwraca None.
    median_by_region: mediana PLN/m² per region (z compute_medians_per_region).
    config: scoring.weights, scoring.risk_by_source, scoring.location_score_by_region, scoring.default_median_price_m2.
    """
    cfg = config or {}
    scoring = cfg.get("scoring") or {}
    price_pln = listing.get("price_pln")
    if price_pln is None or not isinstance(price_pln, (int, float)) or price_pln <= 0:
        return None

    price_pln_f = float(price_pln) / 100.0
    surface = get_surface_m2(listing)
    region = (listing.get("region") or listing.get("city") or "default")
    if isinstance(region, str):
        region = region.strip() or "default"
    else:
        region = "default"
    source = listing.get("source") or "default"
    description = listing.get("description") or ""

    weights = scoring.get("weights") or _DEFAULT_WEIGHTS
    risk_by_source = scoring.get("risk_by_source") or _DEFAULT_RISK_BY_SOURCE
    location_by_region = scoring.get("location_score_by_region") or {}
    default_median = float(scoring.get("default_median_price_m2") or _DEFAULT_MEDIAN_PRICE_M2)

    # Price anomaly (im taniej vs mediana, tym lepiej)
    median_m2 = median_by_region.get(region) or default_median
    if surface and surface > 0 and median_m2 > 0:
        price_per_m2 = price_pln_f / surface
        spread = (median_m2 - price_per_m2) / median_m2
        price_anomaly_norm = max(0.0, min(1.0, (spread + 0.1) / 0.5))
    else:
        price_anomaly_norm = 0.0

    # Yield brutto (czynsz roczny / cena)
    rent = extract_rent_pln_per_month(description)
    if rent is not None and rent > 0:
        yield_brutto = (rent * 12) / price_pln_f
        yield_norm = min(1.0, yield_brutto / 0.10)
    else:
        yield_norm = 0.0

    # Location
    location_norm = float(location_by_region.get(region, _DEFAULT_LOCATION_SCORE))
    location_norm = max(0.0, min(1.0, location_norm))

    # Risk (wyższe = gorzej, odejmujemy)
    risk_norm = float(risk_by_source.get(source, 0.5))
    if _RISK_WORDS.search(description):
        risk_norm = min(1.0, risk_norm + 0.1)
    risk_norm = max(0.0, min(1.0, risk_norm))

    w = weights
    score_raw = (
        price_anomaly_norm * w.get("price_anomaly", _DEFAULT_WEIGHTS["price_anomaly"])
        + yield_norm * w.get("yield", _DEFAULT_WEIGHTS["yield"])
        + location_norm * w.get("location", _DEFAULT_WEIGHTS["location"])
        - risk_norm * w.get("risk", _DEFAULT_WEIGHTS["risk"])
    )
    score = max(0.0, min(100.0, score_raw * 100.0))
    return round(score, 1)
