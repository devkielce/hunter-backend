# Plan: improve scrapers and listing sources

Prioritized, actionable plan to improve data quality, resilience, and coverage.

**Done:** Phase 1.1, 1.2, 1.3, 2.2 (shared `is_likely_error_page` + use in both scrapers + komornik logging) and the defensive DB-level guard in `run.py` (filter before upsert).

---

## Current sources (recap)

| Source        | Type   | Status   | How it runs                    |
|---------------|--------|----------|--------------------------------|
| komornik      | Scraper| Active   | POST /api/run, hunter run      |
| e_licytacje   | Scraper| Active   | Same                           |
| facebook      | Apify  | Active   | POST /webhook/apify (Apify → backend) |
| olx, otodom, gratka | Scraper | In repo only | Not in run pipeline        |

---

## Phase 1: Fix known bugs (high priority)

### 1.1 E-licytacje: skip error pages

**Problem:** Detail pages that show “Brak połączenia z internetem” (or similar error messages) are parsed as valid listings, so bad rows get into the DB.

**Action:**

- In `src/hunter/scrapers/elicytacje.py`, in `_parse_detail()` (or right before `return normalized_listing(...)`):
  - Define a small blocklist of phrases, e.g. `["brak połączenia z internetem", "no internet connection", "błąd", "error"]`.
  - If the parsed `title` (or title + description) matches any phrase (case-insensitive), **return `None`** so the listing is not added.
- Optionally: if `<title>` or main content looks like an error page (e.g. very short, or contains “błąd”), return `None`.

**Acceptance:** Dry-run or run no longer produces listings whose title is “Brak połączenia z internetem”.

---

### 1.2 Komornik: same error-page filter (optional)

**Problem:** Same risk: maintenance or error pages could be parsed as listings.

**Action:**

- In `src/hunter/scrapers/komornik.py`, in `_parse_detail_page()`:
  - Reuse the same blocklist (or a shared helper in `http_utils` or a small `scrapers/common.py`) and return `None` when the parsed title/description clearly indicates an error or “no connection” page.

**Acceptance:** No obviously wrong titles from komornik in the DB.

---

### 1.3 Komornik: 0 listings – diagnostics

**Problem:** `hunter run komornik --dry-run` sometimes returns 0 listings (region filter, empty page, or HTML change).

**Action:**

- Add a small amount of logging in `scrape_komornik()`:
  - After fetching the first list page and parsing rows: log how many rows were found (e.g. “komornik list page 1: N links”).
  - If `items` is empty on page 1, log once “komornik: no links on first page (check region or site structure)”.
- In `config.example.yaml` (and docs), note that `komornik_region: ""` disables the region filter for debugging.

**Acceptance:** Logs make it obvious whether the list is empty vs. detail parsing failed.

---

## Phase 2: Resilience and config

### 2.1 Configurable timeouts per source

**Problem:** Different sites need different timeouts; currently timeouts are hardcoded or a single default.

**Action:**

- In `config.example.yaml`, add under `scraping:` e.g. `httpx_timeout_seconds: 60` (optional).
- In `http_utils.py`, use that value (with a sensible default) for `DEFAULT_TIMEOUT` or for the retry helper.
- In `komornik.py` and `elicytacje.py`, pass that timeout into `sync_get_with_retry(..., timeout=...)` when creating the client or per request.

**Acceptance:** One place in config to increase timeout for slow sites without code change.

---

### 2.2 Shared “error page” / blocklist helper

**Problem:** Blocklist logic will be duplicated between komornik and e_licytacje.

**Action:**

- Add e.g. `src/hunter/scrapers/common.py` (or in `http_utils`) a function:
  - `is_likely_error_page(title: str, description: Optional[str] = None) -> bool`
  - Uses a shared list of phrases (“brak połączenia”, “błąd”, “error”, etc.).
  - Return `True` if title/description matches (case-insensitive).
- Use this in both `_parse_detail_page` (komornik) and `_parse_detail` (e_licytacje) and return `None` when `True`.

**Acceptance:** Single place to extend blocklist; both scrapers stay in sync.

---

## Phase 3: E-licytacje list page (if needed)

### 3.1 Check if list page is JS-rendered

**Problem:** README notes that e-licytacje list page may be JS-rendered (0 links in initial HTML). If we often get 0 or very few links from the list, the site may be rendering links with JS.

**Action:**

- Manually inspect: fetch the list URL with httpx and see if the HTML contains links to `/licytacje/...`. If it does, no change needed.
- If links are missing from the raw HTML:
  - Option A: Add a Playwright (or similar) step **only for the list page**: load the URL, wait for content, extract links, then pass links to the existing detail fetcher (httpx).
  - Option B: Document that e-licytacje list requires a browser and implement a small “list with Playwright, details with httpx” flow in `scrape_elicytacje`.

**Acceptance:** Either we confirm list is server-rendered, or we have a path to get list links via browser.

---

## Phase 4: Komornik coverage (optional)

### 4.1 More categories or regions

**Problem:** Only “mieszkania” (Filter/30) and one region (świętokrzyskie) are used by default.

**Action:**

- Document in `docs/KOMMORNIK_SEARCH_CRITERIA.md` how to add more categories (e.g. 29=domy) if desired (e.g. multiple Filter IDs or config list).
- Optional: add config `scraping.komornik_categories: [30]` and loop over categories in `scrape_komornik()` so new categories don’t require code changes.
- Keep `komornik_region` as is; already documented that `""` means all regions.

**Acceptance:** Clear path to add more komornik categories via config or small code change.

---

## Phase 5: Facebook (Apify) improvements

### 5.1 Optional negative keywords

**Problem:** Some Facebook posts may match sales keywords but be irrelevant (e.g. “nie wynajmę” / “do wynajęcia” when we only want sales).

**Action:**

- In `apify_facebook.py`, add an optional list e.g. `NEGATIVE_KEYWORDS` or config `apify.negative_keywords: ["tylko wynajem", ...]`.
- In `passes_sales_filter()` or in `normalize_facebook_item()`: if text contains any negative keyword (case-insensitive), skip the item (return `None`).
- Document in README or this plan.

**Acceptance:** Config or code allows excluding posts that contain certain phrases.

---

### 5.2 More sales keywords (optional)

**Action:** Review `SALES_KEYWORDS` and add any missing Polish phrases that indicate a real-estate listing (e.g. “sprzedaję mieszkanie”, “oferta sprzedaży”). Keep list in one place and document.

---

## Phase 6: Re-enable OLX / Otodom / Gratka (optional)

**Problem:** These scrapers exist but are not in the run pipeline, so they don’t feed listings.

**Action:**

- In `run.py` and in `webhook_server.py`’s `_run_scrapers_background()`:
  - Import `scrape_olx`, `scrape_otodom`, `scrape_gratka`.
  - Add them to the list of scrapers (e.g. `("olx", scrape_olx)`, etc.).
- In `config.example.yaml`, extend `scraping.sources` with optional `olx`, `otodom`, `gratka` and document that they are optional and may need Playwright (otodom) or different rate limits.
- Ensure schema and Supabase support `source` values `olx`, `otodom`, `gratka` (already in `SOURCE_LITERAL`).
- Test each with `hunter run olx --dry-run` etc. and fix any breakage (sites change).

**Acceptance:** With `sources: [..., "olx"]` (etc.), runs include those scrapers and listings appear in the DB.

---

## Implementation order (suggested)

1. **Phase 1.1** – E-licytacje error-page filter (quick, high impact).
2. **Phase 2.2** – Shared `is_likely_error_page()` and use it in both scrapers (Phase 1.2 becomes trivial).
3. **Phase 1.2** – Komornik error-page filter using the shared helper.
4. **Phase 1.3** – Komornik logging for 0 listings.
5. **Phase 2.1** – Configurable timeouts (optional but useful).
6. **Phase 3.1** – Only if e-licytacje list often has 0 links.
7. **Phases 4, 5, 6** – As needed for coverage and product goals.

---

## Summary table

| Phase | Item | Effort | Impact |
|-------|------|--------|--------|
| 1.1   | E-licytacje: skip error pages | Small | High (stops bad rows) |
| 1.2   | Komornik: skip error pages     | Small | Medium |
| 1.3   | Komornik: logging for 0 results| Small | Debugging |
| 2.1   | Configurable timeouts         | Small | Resilience |
| 2.2   | Shared error-page helper       | Small | Maintainability |
| 3.1   | E-licytacje JS list (if needed)| Medium | Coverage |
| 4.1   | Komornik more categories       | Small | Coverage |
| 5.1   | Facebook negative keywords     | Small | Quality |
| 5.2   | Facebook more keywords        | Tiny  | Coverage |
| 6    | Re-enable OLX/Otodom/Gratka    | Medium | Coverage |

This plan is a living doc: implement in order, then adjust phases as you learn from production runs.
