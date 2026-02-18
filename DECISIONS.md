# Implementation Decisions

Answers to the 10 clarifying questions for the scraping backend.

| # | Topic | Decision |
|---|--------|----------|
| 1 | **Supabase** | Table `listings`; `source_url` UNIQUE; `updated_at`/`created_at`; separate `scrape_runs` with schema below |
| 2 | **Pagination** | Configurable max pages (default 10 for classifieds, 50 for auctions) |
| 3 | **Geographic** | Whole Poland, no city/region filter |
| 4 | **Anti-bot** | Static realistic UA + `Accept-Language: pl-PL,pl;q=0.9` |
| 5 | **Price** | "Zapytaj o cenę" / "Cena do negocjacji" / missing → `price_pln = None` |
| 6 | **Auction date** | Parse Europe/Warsaw → store as UTC ISO string |
| 7 | **Images** | Store all extracted image URLs |
| 8 | **Playwright** | README includes `playwright install`; Linux VPS + optional Docker |
| 9 | **Rate limiting** | 1–2s httpx, 3–5s Playwright (configurable in config) |
| 10 | **Errors** | Skip individual listing; fail scraper only on fatal errors |

## scrape_runs schema

```sql
CREATE TABLE scrape_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  listings_found INT NOT NULL DEFAULT 0,
  listings_upserted INT NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('success', 'error')),
  error_message TEXT
);
```

## listings table (reference)

- `source_url` UNIQUE for upsert
- `updated_at` set on upsert, `created_at` default now()
- `raw_data` JSONB for full scraped payload
