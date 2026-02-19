# Changelog

## 2026-02-19

### Komornik: all regions by default

- **Default region:** Komornik now scrapes **all regions** by default. `config.example.yaml` and `DEFAULT_KOMMORNIK_REGION` use `""` (no filter). Set `komornik_region: "świętokrzyskie"` (or another województwo) in config to limit.
- **Region label:** Each Komornik listing includes a **`region`** field (województwo parsed from the list page, e.g. `podlaskie`, `mazowieckie`) so the frontend can filter by region.
- **Config fix:** When `komornik_region: ""` is set explicitly, the scraper no longer falls back to świętokrzyskie; it correctly treats `""` as “all regions”.

### Schema

- **`region`** added to the normalized listing schema (optional). Used by Komornik; other sources can set it later.

### Config

- **`max_pages_auctions`:** Example and docs use 50 for full scrape (all list pages).
- **`days_back`:** Commented out in example so full scrape keeps all listings; uncomment to filter by auction date.
- **`httpx_delay_seconds`:** Example set to 1.0 (was 1.5).

### Docs

- **docs/FRONTEND_API_RUN_PROXY.md:** Added “Why it works locally but not on Railway”: `config.yaml` is gitignored, so Railway needs `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `APIFY_WEBHOOK_SECRET`. Checklist for 401 (frontend must send `X-Run-Secret`).
- **docs/KOMMORNIK_SEARCH_CRITERIA.md:** Default described as all regions; optional filter; table updated (Województwo = wszystkie domyślnie).
- **docs/BACKEND_SCRAPER_TIMEOUT.md:** New “20 links, 0 in DB” checklist: detail parse, `days_back`, upsert/Supabase, wrong DB/table; quick debug (dry-run, log messages); exact code references and table name.

### On-demand run (no code change, doc alignment)

- **POST /api/run** returns **202 Accepted** and runs scrapers in the background. Frontend should poll **GET /api/run/status** until `completed` or `error`, then refresh listings. See [docs/FRONTEND_API_RUN_PROXY.md](docs/FRONTEND_API_RUN_PROXY.md).
