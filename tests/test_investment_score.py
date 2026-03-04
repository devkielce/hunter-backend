"""Tests for investment score MVP (price anomaly, yield, location, risk)."""
from __future__ import annotations

import pytest

from hunter.investment_score import (
    compute_investment_score,
    compute_medians_per_region,
    extract_rent_pln_per_month,
    get_surface_m2,
)


def test_get_surface_m2_from_raw_data():
    listing = {"raw_data": {"surface_m2": 45.5}}
    assert get_surface_m2(listing) == 45.5


def test_get_surface_m2_from_description():
    listing = {"description": "Mieszkanie 2 pokoje, 62 m², centrum."}
    assert get_surface_m2(listing) == 62.0


def test_extract_rent_pln_per_month():
    assert extract_rent_pln_per_month("Czynsz 2500 zł + media") == 2500
    assert extract_rent_pln_per_month("2500 zł/mies") == 2500
    assert extract_rent_pln_per_month("Brak opisu") is None


def test_compute_medians_per_region():
    listings = [
        {"price_pln": 40000000, "raw_data": {"surface_m2": 50}, "region": "mazowieckie"},
        {"price_pln": 50000000, "raw_data": {"surface_m2": 50}, "region": "mazowieckie"},
    ]
    medians = compute_medians_per_region(listings)
    assert "mazowieckie" in medians
    # 400k PLN/50 m² = 8000, 500k PLN/50 m² = 10000 → median 9000 PLN/m²
    assert medians["mazowieckie"] == 9000.0
    # 40M grosze = 400k PLN, 50m² -> 8000. 50M grosze = 500k PLN, 50m² -> 10000. Median 9000.
    assert medians["mazowieckie"] == 9000.0


def test_compute_investment_score_basic():
    listing = {
        "price_pln": 45000000,
        "raw_data": {"surface_m2": 45},
        "region": "mazowieckie",
        "source": "amw",
        "description": "",
    }
    medians = {"mazowieckie": 12000.0}
    score = compute_investment_score(listing, medians, None)
    assert score is not None
    assert 0 <= score <= 100


def test_compute_investment_score_no_price_returns_none():
    listing = {"price_pln": None, "region": "mazowieckie", "source": "amw"}
    assert compute_investment_score(listing, {}, None) is None
