# Frontend (Next.js) ↔ Backend (hunter-backend) alignment

This doc ensures the **Next.js dashboard** and **Python scraping backend** share the same Supabase schema and semantics.

---

## Shared Supabase schema (single source of truth)

Both apps use the same `listings` and `alert_rules` tables. The backend also uses `scrape_runs` (logging only).

### Listings

| Column         | Type        | Backend writes | Frontend uses |
|----------------|-------------|----------------|---------------|
| id             | UUID        | (auto)         | ✓             |
| title          | TEXT        | ✓              | ✓             |
| description    | TEXT        | ✓              | ✓             |
| price_pln      | BIGINT      | ✓ (grosze)     | ✓ (filters, sort) |
| location       | TEXT        | ✓              | ✓ (filters)   |
| city           | TEXT        | ✓              | ✓ (filters)   |
| source         | TEXT        | ✓              | ✓ (filters)   |
| source_url     | TEXT UNIQUE | ✓ (upsert key) | ✓ (link, index) |
| auction_date   | TIMESTAMPTZ | ✓ (auctions)   | ✓ (countdown) |
| images         | TEXT[]      | ✓ (array URLs) | ✓             |
| raw_data       | JSONB       | ✓              | (optional)     |
| status         | TEXT        | — (DB default) | ✓ (PATCH, filters) |
| notified       | BOOLEAN     | — (DB default) | ✓ (cron digest) |
| created_at     | TIMESTAMPTZ | (auto)         | ✓ ("NEW today") |
| updated_at     | TIMESTAMPTZ | (trigger)      | ✓             |

- **status**: default `'new'` in DB. Backend does **not** send it (so existing rows keep their value on upsert). Frontend updates via `PATCH /api/listings/[id]`.
- **notified**: default `false`. Backend does **not** send it. Frontend sets `true` after sending the email digest.
- **images**: `TEXT[]` so frontend and Apify webhook can use the same type. Backend sends a list of URL strings.

### Sources

- **Backend (this repo)**: **`komornik`**, **`e_licytacje`** (scrapers, run once per day or on demand via `POST /api/run`), **`facebook`** (Apify webhook: `POST /webhook/apify`). Same table, upsert by `source_url`. (OLX, Otodom, Gratka are disabled for now.)
- **Frontend**: Can stop handling Apify webhook; backend owns Facebook ingestion. Optional: keep frontend webhook as fallback.

### alert_rules

Used only by the frontend for the email digest (Resend). Backend does not touch this table. Schema in `supabase_schema.sql`.

---

## What each side does

| Feature | Backend | Frontend |
|--------|---------|----------|
| Fill listings (5 sources) | ✓ Scrapers → Supabase upsert | — |
| Fill listings (Facebook) | ✓ Apify webhook (`hunter webhook` → POST /webhook/apify) | — (optional fallback) |
| Dashboard (filters, sort, count) | — | ✓ |
| Update status | — | ✓ PATCH /api/listings/[id] |
| Countdown to auction | — | ✓ (auction_date) |
| “NEW (today)” badge | — | ✓ (created_at) |
| Email digest (notified) | — | ✓ GET /api/cron/notify, Resend |
| Run frequency | Once per day (scheduler); on demand via `POST /api/run` | Cron 6h for notify (vercel.json) |

---

## Checklist

- [x] `listings` has `status` (default `'new'`) and `notified` (default `false`).
- [x] `listings.images` is `TEXT[]` (backend sends array of strings).
- [x] Backend never sends `status` or `notified` so it doesn’t overwrite frontend/DB values.
- [x] `source_url` UNIQUE for upserts (backend + Apify).
- [x] `alert_rules` table present for frontend cron.
- [x] Same Supabase project: backend uses service role; frontend uses anon + service role for API routes.

Run the same **`supabase_schema.sql`** (taskmaster, single source of truth) in your Supabase SQL editor so both apps stay aligned. It includes RLS with “allow all” for MVP; tighten policies when you add auth.
