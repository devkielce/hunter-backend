# Hunter — Taskmaster

Single source of truth for the **Hunter** system: app description, architecture, schema, APIs, deployment, and document index. Use this for onboarding, alignment between backend and frontend, and operations.

---

## 1. App description

**Hunter** is a production-oriented system for **Polish real estate listings**:

- **Backend (this repo, hunter-backend):** Python scrapers and webhook server. Collects listings from **komornik** (bailiff auctions), **e_licytacje** (court auctions), and **Facebook** (via Apify). Normalizes to a single schema, upserts to **Supabase**, and exposes a webhook for Apify and an on-demand run API for the frontend.
- **Frontend (separate repo):** Next.js dashboard: filters, sort, status (new/contacted/viewed/archived), countdown to auction, “NEW (today)” badge, email digest (Resend), and “Odśwież oferty” (refresh) that triggers the backend run via proxy.
- **Data:** One Supabase project. Tables: `listings` (shared), `alert_rules` (frontend), `scrape_runs` (backend logs). Schema is defined in **`supabase_schema.sql`** — run it once in the Supabase SQL editor; it is the **taskmaster** for both apps.

**Active sources:** komornik, e_licytacje, Facebook (Apify). OLX, Otodom, Gratka are disabled in config but code remains.

**Region:** Backend scrapes **all regions** by default (`komornik_region: ""`, `e_licytacje_region: ""`). Optional config: e.g. `komornik_region: "świętokrzyskie"` to limit. Each Komornik listing has a `region` (województwo) for frontend filtering; the frontend dashboard may describe or filter by a specific region (e.g. Kielce) in the UI.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Apify (Facebook actor)                                                 │
│  Schedule or manual run → on success POST to backend /webhook/apify     │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│  Hunter Backend (this repo)                                             │
│  • hunter webhook     → POST /webhook/apify, POST /api/run, GET /api/run/status
│  • hunter run-all     → Komornik + e_licytacje (CLI or Railway Cron)     │
│  • hunter schedule    → daily scrape (optional)                          │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│  Supabase                                                               │
│  listings (source_url UNIQUE), alert_rules, scrape_runs                  │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│  Frontend (Next.js, separate repo)                                      │
│  Dashboard, filters, PATCH status, cron digest, proxy POST/GET /api/run │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Backend does not start Apify.** Apify runs the actor on a schedule or manually; when the run finishes, Apify calls the backend at `/webhook/apify`. Backend then fetches the dataset from Apify API and upserts to Supabase.
- **Frontend does not call the backend from the browser.** It calls Vercel API routes that proxy to the backend with `X-Run-Secret` for POST /api/run and GET /api/run/status.

---

## 3. Schema (single source of truth)

**File:** [`supabase_schema.sql`](../supabase_schema.sql) — run once in Supabase SQL editor.

### listings

| Column        | Type        | Backend | Frontend | Notes |
|---------------|-------------|---------|----------|--------|
| id            | UUID        | auto    | ✓        | |
| title         | TEXT        | ✓       | ✓        | |
| description   | TEXT        | ✓       | ✓        | |
| price_pln     | BIGINT      | ✓       | ✓        | **Grosze.** Backend parses PLN → grosze; "Zapytaj o cenę" → null. |
| location      | TEXT        | ✓       | ✓        | |
| city          | TEXT        | ✓       | ✓        | |
| source        | TEXT        | ✓       | ✓        | `komornik`, `e_licytacje`, `facebook` |
| source_url    | TEXT UNIQUE | ✓       | ✓        | **Upsert key.** Backend and Apify never send status/notified so existing rows keep values. |
| auction_date  | TIMESTAMPTZ | ✓       | ✓        | Europe/Warsaw parsed → stored UTC ISO. Often null (e.g. Komornik). |
| images        | TEXT[]      | ✓       | ✓        | Array of image URLs. |
| raw_data      | JSONB       | ✓       | (opt)    | Full scraped payload. |
| status        | TEXT        | —       | ✓        | Default `'new'`; frontend PATCH. |
| notified      | BOOLEAN     | —       | ✓        | Default false; frontend sets after digest. |
| last_seen_at  | TIMESTAMPTZ | ✓       | ✓        | Set on each scraper upsert; used for source-archive. |
| removed_from_source_at | TIMESTAMPTZ | —  | ✓        | Set when not seen in last 5 runs; never cleared. Frontend filter by IS NULL. |
| created_at    | TIMESTAMPTZ | auto    | ✓        | "NEW today" badge. |
| updated_at    | TIMESTAMPTZ | trigger | ✓        | |
| region        | TEXT        | ✓ (Komornik) | ✓   | Województwo; optional. Add column if missing; backend retries without it. |

### alert_rules

- Frontend only. Email addresses for digest (Resend). Schema in `supabase_schema.sql`.

### scrape_runs

- Backend only. Logs per run: source, started_at, finished_at, listings_found, listings_upserted, status, error_message.

---

## 4. Backend (hunter-backend)

### Commands

| Command | Purpose |
|--------|---------|
| `hunter run komornik` | Run Komornik scraper only. |
| `hunter run e_licytacje` | Run e_licytacje only. |
| `hunter run-all` | Run all enabled scrapers (komornik, e_licytacje). Use for full scrape (CLI or Railway Cron). |
| `hunter run-all --dry-run` | No DB write; logs sample. |
| `hunter webhook` | Start web server: `/webhook/apify`, `/api/run`, `/api/run/status`. Default `0.0.0.0:5000`; env `PORT`, `HOST`. |
| `hunter schedule` | Blocking: run scrapers once per day (config: cron, timezone). |

### Endpoints (when `hunter webhook` is running)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/webhook/apify` | Apify calls when Facebook actor run succeeds. Body: `datasetId` or `resource.defaultDatasetId`. Header (optional): `x-apify-webhook-secret`. |
| POST | `/api/run` | Start scrapers in background. Returns 202. **No body required** (overrides come from backend config: `on_demand_max_pages_auctions`, etc.). Header (if configured): `X-Run-Secret`. |
| GET | `/api/run/status` | Poll until `status` is `completed` or `error`. Same `X-Run-Secret`. |

### Config

- **File:** `config.yaml` (copy from `config.example.yaml`). Not deployed (gitignored); production uses env vars.
- **Sections:** `supabase` (url, service_role_key), `scraping` (sources, delays, max_pages_auctions, on_demand_max_pages_auctions, komornik_region, e_licytacje_region), `apify` (token, webhook_secret), `run_api` (secret, or fallback to apify.webhook_secret), `logging`, `scheduler`.

### Behaviour

- Upsert always on `source_url`. Full `raw_data` stored. Each upsert sets `last_seen_at` to the run’s finished time.
- **Source-archive:** After each successful run, listings for that source not seen in the last 5 successful runs get `removed_from_source_at` set and `notified = true`; status is preserved. No dis-archive. See [docs/SOURCE_ARCHIVE.md](docs/SOURCE_ARCHIVE.md).
- Price: Polish formats → grosze; "Zapytaj o cenę" / "Cena do negocjacji" → null.
- Auction date: Europe/Warsaw → UTC ISO.
- One bad listing skipped; scraper fails only on fatal errors.
- Rate limits: configurable delay (httpx, Playwright).

---

## 5. Frontend (Hunter dashboard) — summary from frontend taskmaster

The frontend is a **separate repo**. This section summarizes its view for alignment; details live in the frontend’s taskmaster and ALIGNMENT.md.

### Frontend tech stack

| Layer | Choice |
|-------|--------|
| Framework | Next.js 15 (App Router) |
| React | React 19 |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Data | Supabase (service role for server-side listing fetch) |
| E-mail | Resend (digest) |
| Hosting | Vercel (cron for digest; optional fallback for Apify webhook) |

### Frontend routes (for reference)

| Route | Description |
|-------|-------------|
| `GET /` | Home; link to dashboard |
| `GET /dashboard` | Main dashboard: listings, filters, statuses, “Odśwież oferty” |
| `PATCH /api/listings/[id]` | Update listing status (frontend; backend does not touch status) |
| **Odśwież oferty** | **Refetch listings from Supabase only** (do not call POST /api/run). See docs/FRONTEND_API_RUN_PROXY.md. |
| `POST /api/run` | **Proxy** to backend (optional: use only for a separate "Uruchom scrapery" action) |
| `GET /api/run/status` | **Proxy** to backend (poll when scrapers were triggered) |
| `POST /api/apify/webhook` | Apify webhook **fallback** (primary: backend `POST /webhook/apify`) |
| `GET /api/cron/notify` | Daily digest cron (e.g. 8:00 UTC); Resend; sets `notified = true` |

**Apify URL in production:** Prefer backend: `https://hunter.willonski.com/webhook/apify`. Fallback (if used): frontend `https://hunter.willonski.com/api/apify/webhook`. Same header `x-apify-webhook-secret` for both.

### Frontend structure (key files)

- `src/app/layout.tsx` – Root layout (hydration/extension workarounds, Geist fonts).
- `src/app/dashboard/page.tsx` – Server component: fetches listings (4 sources merged), normalizes, passes to dashboard.
- `src/components/ListingDashboard.tsx` – Client: filters, sort, cards grid, status PATCH.
- `src/components/ListingCard.tsx` – Client: card UI, countdown, “NOWE (dzisiaj)”, `suppressHydrationWarning` on time-dependent blocks.
- `RefreshScrapersButtonDynamic` – Client wrapper with `next/dynamic` (ssr: false) for “Odśwież oferty”.

### Frontend done (✅) and optional (🔜)

- **Done:** Next 15, React 19, dashboard with cards/filters/status/countdown/“NOWE (dzisiaj)”/link to offer, Apify fallback webhook, cron digest, Supabase schema alignment, hydration fixes, proxy for `/api/run` and `/api/run/status`.
- **Optional later:** Realtime (Supabase subscription), server-side filters, filters in alert_rules, auth/RLS, table view, alert_rules UI.

### Frontend deployment & env (Vercel)

- **Env:** `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`, `DIGEST_FROM_EMAIL`, `CRON_SECRET`, `BACKEND_URL`, `HUNTER_RUN_SECRET`; optionally `APIFY_TOKEN`, `APIFY_WEBHOOK_SECRET` (for fallback webhook).
- **Cron:** `GET /api/cron/notify` with `Authorization: Bearer <CRON_SECRET>` (e.g. 8:00 UTC in vercel.json).

### Backend ↔ frontend alignment (this repo)

- **Same Supabase project.** Backend uses service role; frontend anon + service role for API routes.
- **Facebook:** Backend owns ingestion via `POST /webhook/apify`. Frontend may keep `POST /api/apify/webhook` as fallback.
- **Run refresh:** Frontend proxies to backend `POST /api/run` and `GET /api/run/status` with `X-Run-Secret` (= `HUNTER_RUN_SECRET` on Vercel = `APIFY_WEBHOOK_SECRET` on backend).
- **POST /api/run:** Backend expects **no body**; overrides (e.g. `on_demand_max_pages_auctions`) come from backend config only. If the frontend repo documents body params (e.g. `days_back`, `max_pages_auctions`), that is not implemented in the backend yet.
- **Schema:** Both use **`supabase_schema.sql`** (this repo) as single source of truth. Frontend may keep a copy (e.g. `supabase-schema.sql`) in sync.
- **Dates:** Use `listing.auction_date \|\| listing.created_at` for display; normalize with `row.created_at != null ? String(row.created_at).trim() : null`; never `String(undefined)`. See docs/DATE_NOT_RENDERING.md and docs/FRONTEND_RENDER_SNIPPET.md.

---

## 6. Apify (Facebook) setup

- **Webhook URL:** `https://hunter.willonski.com/webhook/apify` (or your deployed backend URL).
- **Method:** POST.
- **Headers:** `x-apify-webhook-secret`: same value as backend `apify.webhook_secret` / `APIFY_WEBHOOK_SECRET`.
- **Body:** JSON with `datasetId` or `resource.defaultDatasetId` so backend can fetch dataset.
- **Who starts the run:** Apify (schedule or manual). Backend only reacts to webhook and then fetches dataset from Apify API.

See **docs/APIFY_WEBHOOK_FLOW.md** and **docs/APIFY_INTEGRATION_CHECKLIST.md**.

---

## 7. Deployment

- **Backend (e.g. Railway):** Web service runs `hunter webhook`. Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `APIFY_WEBHOOK_SECRET`, optionally `APIFY_TOKEN`, `PORT`. For full scrape on a schedule, add a **second service** with start command `hunter run-all` and Cron Schedule (e.g. `0 7 * * *`); same env vars, no web.
- **Frontend (e.g. Vercel):** Set `BACKEND_URL`, `HUNTER_RUN_SECRET`; implement proxy routes for `/api/run` and `/api/run/status`.

---

## 8. Document index

| Document | Description |
|----------|-------------|
| **README.md** | Project overview, setup, commands, config, deployment. |
| **DECISIONS.md** | Implementation decisions (Supabase, pagination, price, dates, errors, etc.). |
| **FRONTEND_ALIGNMENT.md** | Shared schema, who does what, checklist. |
| **supabase_schema.sql** | Single schema for backend + frontend; run in Supabase once. |
| **config.example.yaml** | Config template; copy to config.yaml and set secrets. |
| **docs/APIFY_WEBHOOK_FLOW.md** | Who triggers what: Apify → backend webhook → backend fetches dataset. |
| **docs/APIFY_INTEGRATION_CHECKLIST.md** | Apify URL, headers, payload (datasetId), test flow. |
| **docs/FRONTEND_API_RUN_PROXY.md** | Vercel proxy for POST /api/run and GET /api/run/status; env vars; 401 troubleshooting. |
| **docs/SOURCE_ARCHIVE.md** | Listings not seen in last 5 runs get `removed_from_source_at`; frontend filter by IS NULL. |
| **docs/RAILWAY_CRON_FULL_SCRAPE.md** | Second Railway service with Cron Schedule for full `hunter run-all`. |
| **docs/DATE_NOT_RENDERING.md** | Why dates don’t show (select, keys, null, normalization, "undefined"). |
| **docs/FRONTEND_RENDER_SNIPPET.md** | Type, Supabase select, normalizeListing, ListingCard snippet (pl-PL, grosze). |
| **docs/FRONTEND_HYDRATION_CHECKLIST.md** | Hydration-safe date usage. |
| **docs/DATA_IN_DB_NOT_IN_APP.md** | Data present in DB but not in app (filters, select, status, date). |
| **docs/BACKEND_SCRAPER_TIMEOUT.md** | Timeouts, “20 links 0 in DB” checklist. |
| **docs/KOMMORNIK_SEARCH_CRITERIA.md** | Komornik regions, search criteria. |
| **docs/SCRAPER_IMPROVEMENT_PLAN.md** | Scraper improvements and plan. |
| **CHANGELOG.md** | Version history and notable changes. |

**Frontend repo (separate):** The frontend has its own taskmaster, README, ALIGNMENT.md, and docs (e.g. DATA_IN_DB_NOT_IN_APP, BACKEND_RUN_OPTIONS.md, BACKEND_ASYNC_RUN.md, HYDRATION_DEBUG.md, FRONTEND_RENDER_SNIPPET.md). Schema alignment: use this repo’s **supabase_schema.sql** as the single source of truth; frontend ALIGNMENT.md should match FRONTEND_ALIGNMENT.md and the schema here.

---

## 9. Quick reference

| Item | Value |
|------|--------|
| **Dashboard (frontend)** | `https://hunter.willonski.com/dashboard` (Vercel) |
| **Backend webhook URL** | `https://hunter.willonski.com/webhook/apify` (or your backend deployment) |
| **Apify fallback (frontend)** | `https://hunter.willonski.com/api/apify/webhook` (optional) |
| **Run API** | POST `.../api/run`, GET `.../api/run/status`; header `X-Run-Secret`; no body |
| **Schema source of truth** | `supabase_schema.sql` (this repo) |
| **Backend env (production)** | SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APIFY_WEBHOOK_SECRET, APIFY_TOKEN (optional), PORT |
| **Frontend proxy env** | BACKEND_URL, HUNTER_RUN_SECRET (= APIFY_WEBHOOK_SECRET on backend) |
| **Digest cron** | Frontend: GET /api/cron/notify (e.g. 8:00 UTC). Backend: scheduler 10:00 CET Europe/Warsaw (optional). |

---

*This taskmaster is generated from the current codebase and docs. Keep it updated when you change schema, APIs, or deployment.*
