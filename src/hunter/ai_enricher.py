"""AI-powered listing enrichment using Claude API.

For each listing, Claude:
  1. Validates the location is genuinely in the Otwock ~30km area
  2. Checks the description is clear enough to evaluate
  3. Compares price/m² against regional market benchmarks
  4. Generates a concise 2-sentence Polish investment description
  5. Assigns an investment score 0-100

Listings that fail the AI filter (too far, no useful description, overpriced) are
dropped before upsert. The rest are enriched with ai_score, ai_description,
ai_reasoning stored in raw_data.

Market benchmarks for Otwock area (PLN/m²):
  Apartment / lokal:  ~8 000
  House / dom:        ~6 000
  Plot / działka:     ~400
  Commercial:         ~7 000
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from loguru import logger

BATCH_SIZE = 15  # listings per API call — keeps tokens manageable

SYSTEM_PROMPT = """\
Jesteś ekspertem od inwestycji w nieruchomości w Polsce, specjalizującym się \
w regionie Otwocka i okolic (promień ~30 km, województwo mazowieckie).

Benchmarki rynkowe dla tego obszaru (cena/m²):
- Mieszkanie / lokal: ~8 000 PLN/m²
- Dom:               ~6 000 PLN/m²
- Działka budowlana: ~400 PLN/m²
- Komercja:          ~7 000 PLN/m²

Oceniasz oferty z licytacji komorniczych (komornik, e_licytacje), AMW i grup Facebook. \
Twoim celem jest wyłowienie PRAWDZIWYCH okazji — takich, gdzie cena jest poniżej benchmarku \
lub nieruchomość ma potencjał wzrostu.

Odrzucaj (pass: false) gdy:
- Lokalizacja wyraźnie poza rejonem Otwocka (np. inne województwo, odległa gmina)
- Opis jest całkowicie niejasny i nie da się ocenić wartości
- Brak ceny I brak powierzchni (za mało danych)
- Cena ponad 2x wyższa od benchmarku bez wyraźnego uzasadnienia

Zwróć WYŁĄCZNIE valid JSON array, bez żadnego tekstu przed ani po.\
"""

USER_PROMPT_TEMPLATE = """\
Oceń poniższe oferty. Dla każdej zwróć obiekt JSON (w tej samej kolejności co input):

{{
  "pass": true,           // false = odrzuć przed zapisem do bazy
  "ai_score": 75,         // potencjał inwestycyjny 0-100 (100 = rewelacyjna okazja)
  "short_description": "Działka 1100 m² w Steklinie, 30 km od Otwocka. Cena wywołania 278 tys. zł (248 PLN/m²) — 38% poniżej benchmarku działek, potencjał pod zabudowę.",
  "reasoning": "Cena znacznie poniżej rynku, lokalizacja blisko Otwocka, czytelny opis."
}}

Oferty do oceny:
{listings_json}
"""


def _listing_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Compact dict with only fields relevant for AI evaluation."""
    price_pln = row.get("price_pln")
    price_pln_val = round(price_pln / 100) if price_pln else None
    raw = row.get("raw_data") or {}
    surface = raw.get("surface_m2") or row.get("surface_m2")
    price_m2 = row.get("price_per_m2") or raw.get("price_per_m2")
    return {
        "title": (row.get("title") or "")[:120],
        "description": (row.get("description") or "")[:600],
        "city": row.get("city") or "",
        "location": row.get("location") or "",
        "region": row.get("region") or "",
        "source": row.get("source") or "",
        "price_pln": price_pln_val,
        "surface_m2": surface,
        "price_per_m2_calculated": price_m2,
    }


def _extract_json(text: str) -> list[dict]:
    """Extract JSON array from Claude response (handles markdown code fences)."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                text = part
                break
    # Find the outermost [ ... ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def enrich_with_ai(rows: list[dict[str, Any]], config: dict) -> list[dict[str, Any]]:
    """
    Run listings through Claude for investment scoring, filtering, and description generation.

    - Listings that fail AI filter are dropped (not upserted).
    - Passing listings get raw_data.ai_score, raw_data.ai_description, raw_data.ai_reasoning.
    - raw_data.investment_score is overwritten with ai_score.

    Returns: filtered + enriched list.
    """
    ai_cfg = config.get("ai") or {}
    if not ai_cfg.get("enabled"):
        return rows

    api_key = ai_cfg.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("AI enrichment enabled but ANTHROPIC_API_KEY not set — skipping")
        return rows

    try:
        from anthropic import Anthropic
    except ImportError:
        logger.warning("anthropic package not installed — skipping AI enrichment. Run: pip install anthropic")
        return rows

    model = ai_cfg.get("model", "claude-haiku-4-5")
    client = Anthropic(api_key=api_key)
    enriched: list[dict[str, Any]] = []
    total_filtered = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        summaries = [_listing_summary(r) for r in batch]
        listings_json = json.dumps(summaries, ensure_ascii=False, indent=2)

        try:
            response = client.messages.create(
                model=model,
                max_tokens=3000,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(listings_json=listings_json),
                }],
            )
            evaluations = _extract_json(response.content[0].text)

            if len(evaluations) != len(batch):
                logger.warning(
                    "AI returned {} evaluations for {} listings — keeping all (mismatch)",
                    len(evaluations), len(batch),
                )
                enriched.extend(batch)
                continue

            for row, ev in zip(batch, evaluations):
                if not ev.get("pass", True):
                    total_filtered += 1
                    logger.bind(source=row.get("source")).info(
                        "AI rejected: {!r} — {}",
                        (row.get("title") or "")[:60],
                        ev.get("reasoning", ""),
                    )
                    continue

                row.setdefault("raw_data", {})
                ai_score = int(ev.get("ai_score") or 0)
                row["raw_data"]["ai_score"] = ai_score
                row["raw_data"]["ai_description"] = ev.get("short_description", "")
                row["raw_data"]["ai_reasoning"] = ev.get("reasoning", "")
                # AI score overrides the formula-based investment_score
                if ai_score > 0:
                    row["raw_data"]["investment_score"] = ai_score
                enriched.append(row)

        except Exception as e:
            logger.warning(
                "AI enrichment batch {}-{} failed: {} — keeping all rows without AI filter",
                i, i + BATCH_SIZE, e,
            )
            enriched.extend(batch)

    if total_filtered:
        logger.info(
            "AI enrichment: filtered out {} listing(s), {} passed",
            total_filtered, len(enriched),
        )

    return enriched
