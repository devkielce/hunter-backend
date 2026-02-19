# Hunter Backend

Production-oriented scraping backend for **Polish real estate**: **komornik**, **e_licytacje**, **Facebook (Apify)**. Normalized schema, Supabase upserts, scheduling, loguru logging.

## Sources (active)

Obecnie włączone są tylko trzy źródła. Konfiguracja: `scraping.sources`, `scraping.komornik_region`, Apify webhook.

| Source | Tech | Notes |
|--------|------|--------|
| licytacje.komornik.pl | httpx + BeautifulSoup | Bailiff auctions (mieszkania, wszystkie regiony) — [docs/KOMMORNIK_SEARCH_CRITERIA.md](docs/KOMMORNIK_SEARCH_CRITERIA.md) |
| elicytacje.komornik.pl | httpx + BeautifulSoup | Court auctions (Krajowa Rada Komornicza). List page may be JS-rendered (0 links in initial HTML); browser-based fetcher could be added later. |
| Facebook (Apify) | Webhook + Apify API | Dataset → filter (słowa sprzedażowe) → upsert `source=facebook` |

*(OLX, Otodom, Gratka są wyłączone; kod w repo można ponownie włączyć później.)*

## Apify (Facebook)

Zbieranie ofert z Facebooka przeniesione z frontendu do backendu. Apify po zakończeniu aktora wywołuje webhook; backend pobiera dataset, filtruje po słowach sprzedażowych, normalizuje i robi upsert do `listings`.

- **Konfiguracja:** `apify.token` (lub `APIFY_TOKEN`), opcjonalnie `apify.webhook_secret` (lub `APIFY_WEBHOOK_SECRET`) do weryfikacji webhooka.
- **Endpoint:** `POST /webhook/apify` — body (JSON): `datasetId` lub `resource.defaultDatasetId`; nagłówek `x-apify-webhook-secret` jeśli ustawiony.
- **Kiedy i jak wywoływany:** Apify **uruchamia aktora** według harmonogramu lub ręcznie (w Apify Console). Po zakończeniu runu Apify wywołuje webhook na backend; backend pobiera dataset z Apify API i zapisuje do Supabase. Szczegóły: [docs/APIFY_WEBHOOK_FLOW.md](docs/APIFY_WEBHOOK_FLOW.md).
- **Uruchomienie serwera:** `hunter webhook` (domyślnie port 5000; zmienne `PORT`, `HOST`).

## On-demand run (navbar refresh)

The same webhook server exposes **`POST /api/run`** to trigger all scrapers on demand (e.g. “Odśwież oferty”). No body required. Returns **202 Accepted** and runs scrapers in the background; frontend should poll **`GET /api/run/status`** until `status` is `completed` or `error`, then refresh listings.

- **Optional auth:** set `run_api.secret` in config (or use `apify.webhook_secret` as fallback) and send header **`X-Run-Secret: <secret>`**. If no secret is configured, the endpoint is open (suitable only behind a trusted proxy or same origin).
- **CORS:** If the frontend calls the backend from another origin, enable CORS on the server or call `/api/run` from a Next.js API route (server-side) and have the navbar call that route instead. See [docs/FRONTEND_API_RUN_PROXY.md](docs/FRONTEND_API_RUN_PROXY.md) for the exact proxy implementation and env vars.

Szczegóły: pobieranie `GET https://api.apify.com/v2/datasets/{datasetId}/items?token=...`, filtrowanie (sprzedaż, cena, zł, nieruchomość, mieszkanie, dom, licytacja itd.), upsert po `source_url`; `source=facebook`, `price_pln`/`city`/`location` = null.

## Normalized schema

- `title`, `description`, `price_pln` (grosze), `location`, `city`
- `source`, `source_url` (unique, used for upsert)
- `auction_date` (ISO UTC), `images[]`, `raw_data`
- `region` (optional; Komornik sets województwo for frontend filtering). If your Supabase `listings` table doesn’t have a `region` column yet, the backend retries the upsert without it so the run still succeeds; add `region` (text) in the table to persist it.

## Setup

### 1. Python 3.10+

```bash
cd hunter-backend
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e .
```

### 2. Config and secrets

- Copy `config.example.yaml` to `config.yaml` and set `supabase.url`, `supabase.service_role_key`, oraz (dla Apify) `apify.token`.
- Or set env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `APIFY_TOKEN`, opcjonalnie `APIFY_WEBHOOK_SECRET`.

Optional: copy `.env.example` to `.env` and fill (same vars).

### 3. Local testing (no Supabase)

Test scrapers without writing to the DB. **Run one command at a time** (do not paste the whole block or you may get shell errors):

```bash
hunter run komornik --dry-run
```

```bash
hunter run e_licytacje --dry-run
```

```bash
hunter run-all --dry-run
```

Logs show how many listings were found and a sample; no credentials needed.

### 4. Supabase tables

Create in your Supabase SQL editor:

**listings** (ensure `source_url` is UNIQUE for upsert):

```sql
CREATE TABLE IF NOT EXISTS listings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  description TEXT,
  price_pln BIGINT,
  location TEXT,
  city TEXT,
  source TEXT NOT NULL,
  source_url TEXT NOT NULL UNIQUE,
  auction_date TIMESTAMPTZ,
  images JSONB DEFAULT '[]',
  raw_data JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Optional: trigger to set updated_at on row change
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER listings_updated_at
  BEFORE UPDATE ON listings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

**scrape_runs** (for run logs):

```sql
CREATE TABLE IF NOT EXISTS scrape_runs (
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

## Usage

### Run scrapers (with Supabase)

Ensure `config.yaml` or `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are set, then:

```bash
python -m hunter.cli run-all
# or, after pip install -e .:
hunter run-all
```

### Run one scraper

```bash
hunter run komornik
hunter run e_licytacje
```

### Start scheduler (blocking)

Runs all scrapers **once per day** (default: 8:00 Europe/Warsaw). Configure in `config.yaml` under `scheduler` (`cron`, `timezone`).

```bash
hunter schedule
```

### Start webhook server (Apify → Facebook)

Służy do odbierania webhooków od Apify po zakończeniu aktora; pobiera dataset, filtruje i upsertuje do Supabase.

```bash
hunter webhook
```

Domyślnie nasłuchuje na `0.0.0.0:5000`. Zmienne: `PORT`, `HOST`. W Apify ustaw URL webhooka na `https://twoja-domena/webhook/apify` i (opcjonalnie) nagłówek `x-apify-webhook-secret`.

## Config

- **scraping**: `sources`, `komornik_region`, `httpx_delay_seconds`, `playwright_delay_seconds`, `max_pages_classifieds`, `max_pages_auctions`
- **apify**: `token` (lub `APIFY_TOKEN`), `webhook_secret` (opcjonalnie)
- **run_api**: `secret` (opcjonalnie — wymagany nagłówek `X-Run-Secret` dla `POST /api/run`; jeśli brak, używany jest `apify.webhook_secret`)
- **logging**: `level`, `rotation`, `retention`
- **scheduler**: `enabled`, `cron`, `timezone`

See `config.example.yaml`.

## Behaviour

- **Upsert**: always on `source_url`; full `raw_data` stored.
- **Price**: Polish formats → integer grosze; "Zapytaj o cenę" / "Cena do negocjacji" → `null`.
- **Auction date**: parsed as Europe/Warsaw, stored as UTC ISO.
- **Errors**: one bad listing is skipped; scraper fails only on fatal errors.
- **Rate limits**: configurable delay between requests (httpx and Playwright).

## Frontend alignment

The Next.js dashboard (filters, status, countdown, email digest) uses the same Supabase project. **Facebook (Apify)** is now collected by hunter-backend via `POST /webhook/apify`; the frontend can stop handling the Apify webhook or keep it as fallback. See **FRONTEND_ALIGNMENT.md** for the shared schema. **Taskmaster:** `supabase_schema.sql` is the single source of truth. Apply it once in the Supabase SQL editor; use `supabase_migration_add_frontend_fields.sql` only if you already had an older schema.

## Deployment

- **Linux VPS**: install Python, run `playwright install` (and `playwright install-deps` if needed). Use systemd or supervisor for `python -m hunter.cli schedule`.
- **Docker**: use a image with Python + Playwright; run the same commands. Mount `config.yaml` or use env for Supabase.

Logs go to `logs/` with rotation (see `config.yaml`).
