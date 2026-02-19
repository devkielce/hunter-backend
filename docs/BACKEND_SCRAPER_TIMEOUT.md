# "20 links, 0 in DB" — backend checklist

You see **Komornik list page 1: 20 links** (or similar) but almost no rows end up in Supabase. The issue is not "we only had time for one request before timeout" but **"we have 20 links and almost none become rows"**. Fix this in the backend; the frontend does not need changes.

---

## Quick debug

- Run **`hunter run komornik --dry-run`** locally. You get `listings_found` without touching the DB. If that’s 0 (or very low) while the log says "20 links", the loss is in **detail parse** or **days_back** inside the scraper.
- In logs, look for **"Skip listing &lt;url&gt;: …"** (detail fetch/parse exception) and **"Skipped N listing(s) as likely error pages before upsert"** (`hunter.run`). Those explain missing rows.

---

## 1. Detail fetch/parse failing

The list page returns 20 links, but when the backend fetches each **detail** page:

- The URL might be wrong, or
- The page HTML may have changed so the parser no longer finds title/price/date/location, or
- **`is_likely_error_page(title, description)`** returns true and the scraper returns `None` for that listing.

**Result:** `_parse_detail_page()` returns `None` or an exception is caught; no (or almost no) valid listing rows.

**Check:**

- List URL: `https://licytacje.komornik.pl/Notice/Filter/30` (and `?page=N` for next pages). Detail URLs look like `…/Notice/Details/&lt;id&gt;`.
- Log or open one **detail URL** in a browser and confirm it’s a real listing page (not error/captcha/redirect).
- In **`src/hunter/scrapers/komornik.py`**, `_parse_detail_page` uses: `h1, .title, .auction-title, [class*='title']` for title; `.description, .content, [class*='description']` for description; `[class*='price']`, `[class*='cena']`, `.value` for price; `[class*='location']`, `[class*='address']`, `[class*='miejsce']` for location; `[class*='date']`, `[class*='termin']`, `[class*='auction-date']` for date. If the site changed structure, update these selectors.
- Optionally log length or a short snippet of the first detail HTML to confirm you get a normal page.

---

## 2. Filter dropping everything

If **`days_back`** (e.g. `1`) is set in config, only listings with `auction_date` within the last N days are kept **inside the scraper** (`scrape_komornik` in `src/hunter/scrapers/komornik.py`). If all 20 are older, you get **0 rows** in `results` and thus 0 sent to the DB.

**Check:**

- In **`config.yaml`** (or Railway env), comment out or remove **`days_back`** and run again. If rows appear, the filter was the cause.
- In **`config.example.yaml`**, `days_back` is commented out by default so a full scrape keeps all parsed listings.

---

## 3. Upsert not called or failing

The flow in **`hunter.run.run_scraper`** is: `scrape_fn(cfg)` → filter with **`is_likely_error_page`** → **`for_supabase(r)`** → **`upsert_listings(client, prepared)`** in **`hunter.supabase_client`**. If an exception is raised before or inside `upsert_listings`, no rows are written.

**Check:**

- Railway/service logs: look for tracebacks or **"Supabase upsert failed"** (logged in `supabase_client.upsert_listings`).
- Backend credentials: **`SUPABASE_URL`** and **`SUPABASE_SERVICE_ROLE_KEY`** (or from config). Wrong or missing credentials cause connection/auth errors.
- Supabase dashboard → Logs: failed requests from the backend. Table **`listings`** must exist; upsert uses **`on_conflict="source_url"`**. Check RLS and schema (required columns, types) so the payload is accepted.

---

## 4. Wrong DB/table

The backend might be writing to a **different Supabase project or table** than the one the frontend reads from.

**Check:**

- Backend uses **`hunter.config.get_config()`** (and env **`SUPABASE_URL`** on Railway). Frontend: which Supabase project/table it queries.
- Backend writes to table **`listings`** (see **`hunter.supabase_client.LISTINGS_TABLE`**). Ensure the frontend reads from the same project and the same **`listings`** table.

---

## Summary

| Step | Where | What to do |
|------|--------|------------|
| List | `komornik._parse_list_page` | You see "20 links" → list parsing is OK. |
| Detail | `komornik._parse_detail_page`, `is_likely_error_page` | Verify detail URLs and HTML; fix selectors or error-page logic if the site changed. |
| Filter | `scraping.days_back` in config | Try without `days_back`; confirm rows are not all filtered out. |
| Upsert | `run.run_scraper` → `supabase_client.upsert_listings` | Check logs for exceptions; verify Supabase credentials and that upsert is called and succeeds. |
| DB/table | `SUPABASE_URL`, `listings` | Ensure backend and frontend use the same Supabase project and `listings` table. |

After fixing the backend so that the 20 links become parsed rows and are upserted to the correct table, the frontend will show them without any change.
