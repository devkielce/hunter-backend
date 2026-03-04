"""Tests for short title extraction (no AI): one-sentence titles from description."""
from __future__ import annotations

import pytest

from hunter.title_extractor import extract_short_title


def test_mieszkanie_2_pokoje_metraz():
    text = "Wynajmę mieszkanie 2 pokoje 45 m² w centrum, ul. Kwiatowa."
    assert "Mieszkanie" in extract_short_title(text, fallback="X")
    assert "2-pokojowe" in extract_short_title(text, fallback="X")
    assert "45 m²" in extract_short_title(text, fallback="X")


def test_dom_3_kondygnacje():
    text = "Sprzedam dom 3 kondygnacje, stan do remontu."
    result = extract_short_title(text, fallback="X")
    assert "Dom" in result
    assert "kondygnacj" in result.lower()


def test_kawalerka_metraz():
    text = "Kawalerka 28 m2, wynajem od zaraz."
    result = extract_short_title(text, fallback="X")
    assert "Kawalerka" in result
    assert "28 m²" in result


def test_dzialka_metraz():
    text = "Działka budowlana 500 m², media przy działce."
    result = extract_short_title(text, fallback="X")
    assert "Działka" in result
    assert "500 m²" in result


def test_lokal_uzytkowy():
    text = "Lokal użytkowy 120 m², parter."
    result = extract_short_title(text, fallback="X")
    assert "Lokal użytkowy" in result
    assert "120 m²" in result


def test_fallback_when_nothing_matches():
    text = "Super oferta, zadzwoń po szczegóły."
    result = extract_short_title(text, fallback="Oferta specjalna")
    assert result == "Oferta specjalna"


def test_fallback_empty_text():
    assert extract_short_title("", fallback="Brak") == "Brak"
    assert extract_short_title("   ", fallback="X") == "X"


def test_first_line_when_no_type_and_no_fallback():
    text = "Mam do wynajęcia coś fajnego.\nCena 2000 zł."
    result = extract_short_title(text, fallback=None)
    assert "Mam do wynajęcia" in result or "coś" in result or result == "Oferta"


def test_powierzchnia_keyword():
    text = "Mieszkanie 3 pokoje, pow. 65 m²."
    result = extract_short_title(text, fallback="X")
    assert "Mieszkanie" in result
    assert "3-pokojowe" in result
    assert "65 m²" in result
