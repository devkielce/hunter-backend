"""Geographic filter: mazowieckie region + Otwock area (within ~30km).

Cities within ~30km of Otwock (52.106°N, 21.264°E) in mazowieckie voivodeship.
Static list — no external geocoding needed.
"""
from __future__ import annotations

from typing import Optional

TARGET_REGION = "mazowieckie"

# Cities, districts, and gminas within ~30km of Otwock.
# Both Polish characters and ASCII equivalents included for fuzzy matching.
OTWOCK_AREA_CITIES: frozenset[str] = frozenset({
    # Centre
    "otwock",
    # ~5–15km
    "józefów", "jozefow",
    "falenica",
    "wawer",
    "wesoła", "wesola",
    "karczew",
    "wiązowna", "wiazowna",
    "celestynów", "celestynow",
    # Warsaw (large city; some listings just say "warszawa")
    "warszawa", "warsaw",
    # Warsaw districts
    "rembertów", "rembertow",
    "praga-południe", "praga południe", "praga poludnie",
    "ursynów", "ursynow",
    # ~15–25km
    "sulejówek", "sulejowek",
    "konstancin", "konstancin-jeziorna",
    "halinów", "halinow",
    "sobienie-jeziory", "sobienie jeziory",
    "osieck",
    "góra kalwaria", "gora kalwaria",
    # ~25–30km
    "piaseczno",
    "lesznowola",
    "mińsk mazowiecki", "minsk mazowiecki",
    "pilawa",
    "kołbiel", "kolbiel",
    "wilga",
    # Small localities in the area
    "całowanie", "calowanie",
    "wola karczewska",
    "glinianka",
    "ostrówek", "ostrowek",
    "karpiska",
    "ponurzyca",
    "świerk", "swietk", "swierc",
})


def _normalize(s: str) -> str:
    return (s or "").lower().strip()


def is_in_target_area(
    region: Optional[str],
    city: Optional[str],
    location: Optional[str],
) -> bool:
    """
    Returns True if listing is in mazowieckie AND in Otwock ~30km area.
    - If region is provided and not mazowieckie → False.
    - If region is unknown (None/empty), still pass through (don't reject stubs).
    - City/location must match one of the known Otwock-area names.
    """
    region_n = _normalize(region)
    city_n = _normalize(city)
    location_n = _normalize(location)

    # Region must be mazowieckie (or unknown — stubs may lack region)
    if region_n and TARGET_REGION not in region_n:
        return False

    # City/location must contain an Otwock-area name
    combined = f"{city_n} {location_n}"
    return any(c in combined for c in OTWOCK_AREA_CITIES)


def is_geo_filter_enabled(config: dict) -> bool:
    """Returns True when geo_filter.enabled is True in config. Default False."""
    return bool((config.get("geo_filter") or {}).get("enabled", False))
