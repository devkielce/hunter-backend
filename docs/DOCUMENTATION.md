# Hunter — Documentation (unified)

Single reference for the Hunter system: **how a scrape run (task) is generated and executed**, how run metrics are calculated, schema, APIs, deployment, and troubleshooting.

---

## 1. How a scrape run (task) is generated and executed — step by step

A **scrape run** (the “task”) is one execution of one or all scrapers that produces listings and writes them to Supabase, and logs a row per source in **scrape_runs**. Here is how that run is **generated** (triggered) and **executed**, step by step.

### 1.1 How the run is triggered (task generation)

A run can be started in three ways:

| Trigger | How | Where |
|--------|-----|-------|
| **CLI** | You run `hunter run-all` or `hunter run komornik` (etc.) in a terminal. | `hunter.cli` → `run_all()` or `run_one()` |
| **Railway Cron** | A separate Railway service has **Start command** `hunter run-all` and a **Cron Schedule** (e.g. `30 12 * * *`). Railway starts the process at that time; the process runs scrapers once and exits. | Same as CLI: `run_all()` |
| **POST /api/run** | The frontend (or a tool) calls **POST /api/run** on the web server. The server starts a **background thread** that runs all scrapers and does **not** block the request. | `webhook_server.api_run()` → `_run_scrapers_background()` in a daemon thread |

So the “task” is **generated** by: (1) you or cron running the CLI, or (2) an HTTP POST to `/api/run` that spawns the background thread.

### 1.2 Execution steps (after the run is started)

**Path A — CLI or Railway Cron (`hunter run-all` or `hunter run X`):**

1. **Entry:** `run_all(config, dry_run)` or `run_one(source, config, dry_run)` in `run.py` is called. Logging is set up from config.
2. **Scraper list:** `run_all` builds the list of scrapers from `[(komornik, scrape_komornik), (e_licytacje, scrape_elicytacje), (amw, scrape_amw)]` and optionally filters by `config.scraping.sources`. `run_one` runs only the requested source.
3. **Per scraper:** For each `(name, scrape_fn)`, `run_scraper(name, scrape_fn, config, dry_run)` is called (see below). Results are not aggregated in memory for CLI; each `run_scraper` writes to Supabase and to **scrape_runs**.
4. **End:** Process exits. No HTTP response; logs and **scrape_runs** table hold the outcome.

**Path B — POST /api/run (background thread):**

1. **Entry:** Client sends **POST /api/run** (with optional `X-Run-Secret`). Server checks secret (if configured), then checks that no run is already in progress (`_run_state["status"] != "running"`).
2. **State set:** Under lock: `_run_state["status"] = "running"`, `_run_state["started_at"] = now()`, `results` and `error` cleared.
3. **Response:** Server returns **202 Accepted** with `{ "ok": true, "status": "started", "message": "..." }`. The request ends here; the client must poll **GET /api/run/status** for completion.
4. **Background thread:** A daemon thread runs `_run_scrapers_background()`. Config is loaded; optional **on_demand** overrides are applied (`on_demand_max_pages_auctions`, `on_demand_max_listings`) so the API-triggered run is shorter.
5. **Scraper list:** Same list as CLI (komornik, e_licytacje, amw), optionally filtered by `config.scraping.sources`. For each source, `run_scraper(name, fn, cfg_for_scraper, dry_run=False)` is called. Each result `(found, upserted, status, error_message)` is appended to a **results** array.
6. **State updated:** When all scrapers finish (or one fails), under lock: `_run_state["status"] = "completed"` or `"error"`, `_run_state["finished_at"] = now()`, `_run_state["results"] = results`, `_run_state["error"] = None` or the exception message.
7. **Polling:** Client calls **GET /api/run/status**; server returns `{ ok, status, started_at, finished_at, results, error }`. When `status === "completed"`, **results** contains the per-source metrics.

**Common execution (inside each `run_scraper` call):**

1. **started_at** = now(); **listings_found** = 0, **listings_upserted** = 0, **status** = "success".
2. **Scrape:** `rows = scrape_fn(cfg)` — the actual scraper runs (HTTP requests, parse HTML, normalize to listing dicts).
3. **listings_found** = len(rows).
4. If **dry_run**: return (listings_found, 0, "success", None); no DB.
5. If **rows** empty: insert **scrape_runs** row (0, 0, success); run **archive** for this source; return.
6. **Clean:** Drop rows where `is_likely_error_page(title, description)`; convert rest with `for_supabase()` and set `last_seen_at`.
7. **Upsert:** `listings_upserted = upsert_listings(client, prepared)`.
8. Insert **scrape_runs** row (listings_found, listings_upserted, status, error_message); run **archive** on success.
9. Return (listings_found, listings_upserted, status, error_message). On exception: log **scrape_runs** with status "error" and return.

So the **task** is: one or more such `run_scraper` executions, either in the main process (CLI/Cron) or in the background thread (POST /api/run), each producing **scrape_runs** rows and updated **listings** in Supabase.

---

## 2. How run metrics (“performance”) are calculated — step by step

The backend does **not** compute a “performance score.” It computes **run metrics** for each scraper run: **listings_found**, **listings_upserted**, and **status**. Here is how they are produced, step by step.

### 2.1 Where it happens

- **Code:** `src/hunter/run.py` → `run_scraper()`, and `src/hunter/webhook_server.py` → `_run_scrapers_background()` + `GET /api/run/status`.
- **Persistence:** Each run is logged to the **scrape_runs** table: `source`, `started_at`, `finished_at`, `listings_found`, `listings_upserted`, `status`, `error_message`.

### 2.2 Step-by-step flow (per scraper)

1. **Start**  
   `run_scraper(name, scrape_fn, config, dry_run)` is called (e.g. for `komornik`, `e_licytacje`, `amw`).  
   `started_at = now()` (UTC ISO).  
   `listings_found = 0`, `listings_upserted = 0`, `status = "success"`.

2. **Scrape**  
   `rows = scrape_fn(cfg)` runs the scraper.  
   The scraper returns a list of normalized listing dicts (one per offer).

3. **listings_found**  
   `listings_found = len(rows)` — count of all listings returned by the scraper (before any DB or filtering).

4. **Dry-run branch**  
   If `dry_run=True`: log the count and a sample; **return** `(listings_found, 0, "success", None)`. No Supabase, no `scrape_runs` row for dry-run.

5. **Empty results**  
   If `rows` is empty: insert a **scrape_runs** row with `listings_found=0`, `listings_upserted=0`, `status="success"`; run **archive** (listings not seen in last 5 runs); **return** `(0, 0, "success", None)`.

6. **Clean rows**  
   Rows are filtered with `is_likely_error_page(title, description)`; any row that looks like an error page is dropped.  
   Remaining rows are converted with `for_supabase(r)` and each gets `last_seen_at = finished_at`.

7. **Upsert**  
   `listings_upserted = upsert_listings(client, prepared)` — Supabase upsert on `source_url`.  
   The return value is the number of rows actually upserted (inserted or updated).

8. **Success log**  
   A **scrape_runs** row is inserted: `listings_found`, `listings_upserted`, `status="success"`, `error_message=None`.  
   **Archive** runs: listings for this source not seen in the last 5 successful runs get `removed_from_source_at` set.

9. **Return (success)**  
   Returns `(listings_found, listings_upserted, "success", None)`.

10. **Exception path**  
    If the scraper or upsert raises:  
    `status = "error"`, `error_message = str(e)`.  
    A **scrape_runs** row is still written with the current `listings_found`, `listings_upserted`, `status="error"`, `error_message`.  
    Returns `(listings_found, listings_upserted, "error", error_message)`.

### 2.3 What the API returns

- **POST /api/run**  
  Returns **202** with `{ "ok": true, "status": "started", "message": "..." }`. No metrics yet; run is in the background.

- **GET /api/run/status**  
  When `status === "completed"`: body includes **results**, an array of per-source objects:
  - `source` (e.g. `"komornik"`, `"amw"`)
  - `listings_found` — number of listings returned by the scraper
  - `listings_upserted` — number of rows upserted to Supabase
  - `status` — `"success"` or `"error"`
  - `error_message` — set only when `status === "error"`

So “performance” in the sense of “how did the run do?” is exactly: **listings_found** (how many offers were scraped) and **listings_upserted** (how many made it into the DB), per source, plus **status** and optional **error_message**.

---

## 3. App description and architecture

**Hunter** is a system for **Polish real estate listings**:

- **Backend (this repo):** Python scrapers (komornik, e_licytacje, amw) and webhook server. Collects listings, normalizes to one schema, upserts to **Supabase**, exposes `/webhook/apify` and **POST /api/run**, **GET /api/run/status**.
- **Frontend (separate repo):** Next.js dashboard: filters, status, countdown, “Odśwież oferty”, email digest. Reads from same Supabase.
- **Data:** One Supabase project. Tables: `listings`, `alert_rules`, `scrape_runs`. Schema: **supabase_schema.sql** (run once in Supabase).

**Active sources:** komornik, e_licytacje, amw; Facebook via Apify webhook. OLX, Otodom, Gratka are in repo but not in the run pipeline.

```
Apify (Facebook) → POST /webhook/apify → Backend fetches dataset → Supabase
Backend: hunter webhook (POST/GET /api/run), hunter run-all (CLI or Railway Cron)
Supabase ← Backend
Frontend (Next.js) ← Supabase; proxy to Backend for POST/GET /api/run
```

---

## 4. Schema (single source of truth)

**File:** `supabase_schema.sql` — run once in Supabase SQL editor.

- **listings:** id, title, description, price_pln (grosze), location, city, source, source_url (UNIQUE, upsert key), auction_date, images, raw_data, status, notified, last_seen_at, removed_from_source_at, created_at, updated_at, region.
- **alert_rules:** frontend only (digest). Backend does not touch it.
- **scrape_runs:** source, started_at, finished_at, listings_found, listings_upserted, status, error_message. Backend only.

**Frontend–backend alignment (listings):** Backend writes title, description, price_pln, location, city, source, source_url, auction_date, images, raw_data, last_seen_at, region; backend does **not** send status or notified (so existing rows keep values on upsert). Frontend uses all columns (filters, sort, PATCH status, countdown, “NEW today”, digest). Same Supabase project; run **supabase_schema.sql** once so both apps stay aligned.

**Checklist:** listings has status (default `'new'`), notified (default false), images as TEXT[]; source_url UNIQUE; backend never overwrites status/notified; alert_rules present for frontend cron.

---

## 5. Backend (hunter-backend)

### Commands

| Command | Purpose |
|--------|---------|
| `hunter run komornik` \| `e_licytacje` \| `amw` | Run one scraper. |
| `hunter run-all` | Run all enabled scrapers. Use for full scrape (CLI or Railway Cron). |
| `hunter run-all --dry-run` | No DB write; logs sample and counts. |
| `hunter webhook` | Start server: `/webhook/apify`, `/api/run`, `/api/run/status`. Default `0.0.0.0:5000`; env `PORT`, `HOST`. |
| `hunter schedule` | Blocking: run scrapers once per day (config cron, timezone). |

### Endpoints (when `hunter webhook` is running)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/webhook/apify` | Apify calls when Facebook actor run succeeds. Body: `datasetId` or `resource.defaultDatasetId`. Header (optional): `x-apify-webhook-secret`. |
| POST | `/api/run` | Start scrapers in background. Returns 202. No body required. Header (if configured): `X-Run-Secret`. |
| GET | `/api/run/status` | Poll until `status` is `completed` or `error`. Returns `results` with per-source `listings_found`, `listings_upserted`, `status`, `error_message`. |

### Config

- **File:** `config.yaml` (copy from `config.example.yaml`). Production: env vars (e.g. Railway).
- **Sections:** `supabase`, `scraping` (sources, delays, max_pages_auctions, on_demand_max_pages_auctions, komornik_region, etc.), `apify`, `run_api`, `logging`, `scheduler`.

### Behaviour

- Upsert on `source_url`. Each upsert sets `last_seen_at`.
- **Source-archive:** After each successful run, listings for that source not seen in the last 5 successful runs get `removed_from_source_at` and `notified = true`. Frontend should filter with `removed_from_source_at IS NULL`.
- Price: Polish formats → grosze; "Zapytaj o cenę" → null. Auction date: Europe/Warsaw → UTC ISO.

---

## 6. Source-archive (listings not seen in last 5 runs)

After each **successful** run per source, the backend marks listings as "removed from source" if they were **not seen in the last 5 successful runs** for that source.

- **Columns:** `last_seen_at` (set on every upsert), `removed_from_source_at` (set by archive step).
- **When:** Archive runs only when the source has at least 5 successful runs in `scrape_runs`. Cutoff = 5th-to-last run’s `started_at`; listings with `last_seen_at < cutoff` or `last_seen_at IS NULL` get `removed_from_source_at = now()` and `notified = true`. Status is not changed.
- **No dis-archive:** Once set, `removed_from_source_at` is never cleared by the backend.
- **Frontend:** Filter with `removed_from_source_at IS NULL` by default.
- **Migration:** Run `supabase_migration_source_archive.sql` once to add columns, trigger, and RPC.

---

## 7. Railway: full scrape (Cron job)

To run a **full** scrape (all pages) that runs as long as needed and writes to the DB, use a **separate Railway service** with **Cron Schedule**:

1. New service from same repo. **Start command:** `hunter run-all` (do **not** use `hunter schedule`).
2. **Cron:** e.g. `30 12 * * *` (13:30 CET in winter, UTC). Railway cron uses UTC.
3. **Same env as web:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (and optional `APIFY_TOKEN`).
4. This service does not serve HTTP; it runs scrapers once and exits.

Web service can keep **POST /api/run** for a quick refresh (e.g. with `on_demand_max_pages_auctions: 10`).

---

## 8. Frontend: proxy for POST /api/run and “Odśwież oferty”

- **Odśwież oferty (recommended):** Only **refetch listings from Supabase**. Do **not** call POST /api/run from this button. Use your existing data-fetch (e.g. React Query `refetch()`).
- **Optional:** A separate “Uruchom scrapery” button can call **POST /api/run** (via Vercel proxy), then **poll GET /api/run/status** until `status === "completed"` or `"error"`, then refetch listings.

**Backend contract:**

- **POST /api/run:** No body. Headers: `X-Run-Secret` (if configured). 202 = started; 409 = run already in progress; 401 = wrong/missing secret.
- **GET /api/run/status:** Same `X-Run-Secret`. 200 body: `{ ok, status, started_at, finished_at, results, error }`. When `status === "completed"`, `results` is an array of `{ source, listings_found, listings_upserted, status, error_message }`.

**Vercel env:** `BACKEND_URL`, `HUNTER_RUN_SECRET` (= `APIFY_WEBHOOK_SECRET` on backend). Implement two proxy routes: POST `/api/run` and GET `/api/run/status`, both forwarding to Railway with `X-Run-Secret`.

**401 fix:** Ensure proxy sends `X-Run-Secret`, `HUNTER_RUN_SECRET` is set on Vercel, value matches Railway `APIFY_WEBHOOK_SECRET`, and redeploy after env change.

---

## 9. Apify (Facebook) flow and integration

- **Who triggers:** Apify (schedule or manual). Backend does **not** start the actor.
- **When backend is called:** When the Apify actor run **finishes**, Apify POSTs to your **webhook URL** (e.g. `https://your-backend.up.railway.app/webhook/apify`).
- **Backend then:** Verifies `x-apify-webhook-secret` (if set), reads `datasetId` or `resource.defaultDatasetId`, fetches `GET https://api.apify.com/v2/datasets/{id}/items?token=...`, filters by sales keywords, normalizes, upserts to Supabase, returns 200 with `listings_found` and `listings_upserted`.

**Checklist:** URL = POST /webhook/apify; header `x-apify-webhook-secret` = same as backend; body JSON with `datasetId` or `resource.defaultDatasetId`; Content-Type application/json. Backend needs `APIFY_TOKEN` (or `apify.token`) to fetch the dataset.

---

## 10. Komornik search criteria

- **Source:** https://licytacje.komornik.pl. List: `/Notice/Filter/30` (mieszkania). Pagination: `?page=2`, …
- **Region:** Default all; optional `scraping.komornik_region` (e.g. `"świętokrzyskie"`) filters by column “Miasto (Województwo)”.
- **Limit:** `scraping.max_pages_auctions` (default 50).

---

## 11. Backend scraper timeout / “20 links, 0 in DB”

If you see “20 links” but almost no rows in Supabase:

1. **Detail fetch/parse:** Wrong URL, changed HTML, or `is_likely_error_page` dropping rows. Check detail URL in browser; update selectors in `komornik.py` / `elicytacje.py`.
2. **Filter:** `days_back` in config can drop all listings if they’re older than N days. Try without `days_back`.
3. **Upsert:** Check logs for exceptions; verify `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`; confirm `listings` table and `source_url` unique.
4. **Same DB:** Backend and frontend must use the same Supabase project and `listings` table.

Run `hunter run komornik --dry-run` to see `listings_found` without DB.

---

## 12. Scraper improvement plan (summary)

- **Done:** Shared `is_likely_error_page`, Komornik/e_licytacje error-page filter, Komornik logging, defensive filter before upsert in run.py.
- **Optional:** Configurable timeouts; e_licytacje list page JS (Playwright if needed); Komornik more categories; Facebook negative keywords; re-enable OLX/Otodom/Gratka via config.

---

## 13. Frontend: render, dates, hydration, data not showing

### Render and types

- Use **snake_case** from API: `auction_date`, `created_at`, `price_pln`. **price_pln** = grosze (divide by 100 for PLN).
- **Listing type:** id, title, description, price_pln, location, city, source, source_url, auction_date, created_at, updated_at, images, status, region. Include `auction_date`, `created_at`, `updated_at` in Supabase `.select()`.
- **Normalize:** Never `String(row.created_at)` when it can be undefined (becomes `"undefined"`). Use `row.created_at != null ? String(row.created_at).trim() : null`. Same for `updated_at`, `auction_date`.
- **Display date:** Use `listing.auction_date || listing.created_at`; if `auction_date` set show “Licytacja: …”, else “Dodano: …” with `created_at`.
- **Price:** `listing.price_pln != null ? (listing.price_pln / 100).toFixed(0) : null` then show with “zł”.

### Date not rendering

- Ensure columns are in `.select()`. Use snake_case. Guard null before formatting. Parse with `new Date(listing.auction_date)`. Avoid `String(undefined)` in normalization.

### Hydration

- Avoid different server vs client output: use deterministic date format (e.g. `toISOString().slice(0, 10)`) or format only after mount (e.g. inside `useMounted()`). No `Date.now()` or `Math.random()` in first render. Stable keys (`item.id`), no mutating server props.

### Data in DB but not in app

- **Same Supabase project:** Frontend `NEXT_PUBLIC_SUPABASE_URL` must match backend `SUPABASE_URL`.
- **Filters:** Don’t exclude source (e.g. komornik) or status; check `removed_from_source_at IS NULL` if you use archive.
- **Table/RLS:** Query `listings`; with service role RLS is bypassed; with anon key ensure policy allows read.

---

## 14. Implementation decisions (reference)

| Topic | Decision |
|--------|----------|
| Supabase | Table listings; source_url UNIQUE; updated_at/created_at; separate scrape_runs |
| Pagination | Configurable max pages (default 10 classifieds, 50 auctions) |
| Geographic | Whole Poland; optional komornik_region / e_licytacje_region filter |
| Anti-bot | Static realistic User-Agent + Accept-Language: pl-PL |
| Price | "Zapytaj o cenę" / "Cena do negocjacji" / missing → price_pln = null |
| Auction date | Parse Europe/Warsaw → store UTC ISO |
| Images | Store all extracted image URLs (TEXT[]) |
| Rate limiting | 1–2s httpx, 3–5s Playwright (configurable) |
| Errors | Skip individual listing; fail scraper only on fatal errors |

scrape_runs: id, source, started_at, finished_at, listings_found, listings_upserted, status (success|error), error_message.

---

## 15. Quick reference

| Item | Value |
|------|--------|
| How a run (task) is generated | CLI (`hunter run-all` / `hunter run X`), Railway Cron (`hunter run-all`), or POST /api/run (background thread). See §1. |
| Run metrics | listings_found, listings_upserted, status (per source); from GET /api/run/status when status=completed |
| Schema | supabase_schema.sql (this repo) |
| Backend env | SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APIFY_WEBHOOK_SECRET, APIFY_TOKEN (optional), PORT |
| Frontend proxy env | BACKEND_URL, HUNTER_RUN_SECRET (= APIFY_WEBHOOK_SECRET on backend) |
| Full scrape | Railway Cron service: start `hunter run-all`, cron e.g. `30 12 * * *`, same SUPABASE_* vars |

---

*This is the single unified documentation. All former separate docs (taskmaster, frontend alignment, decisions, Apify, Railway, Komornik, etc.) are merged here. Schema and migrations: supabase_schema.sql, supabase_migration_*.sql in repo root.*
