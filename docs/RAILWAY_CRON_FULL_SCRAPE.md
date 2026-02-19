# Full scrape on Railway: run as long as needed (Cron job)

When the web service runs the scrapers in a **background thread** after POST /api/run, the **container can be stopped** (e.g. idle timeout, recycle) before the run finishes, so nothing is written to the DB.

To run the **full** scrape (all pages) and let it **run as long as needed** until it finishes and writes to the DB, use a **separate Railway service** that runs only on a **Cron Schedule**. That service runs `hunter run-all`, exits when done, and is not tied to the web process.

---

## 1. Add a second service for the scrape (Cron)

In your Railway project:

1. **New service from same repo**  
   Add a new service that uses the **same** repository (hunter-backend).  
   - If you use “Deploy from GitHub”, add another service and connect the same repo, or duplicate the existing service and change its role.

2. **Start command = run scrapers and exit**  
   In the new service → **Settings** → **Deploy** (or **Build & Deploy**):
   - Set **Start Command** (or **Custom Start Command**) to:
     ```bash
     hunter run-all
     ```
   - Do **not** run the web server (no `gunicorn`, no `hunter webhook`) in this service. This service should only run the scrapers and exit.

3. **Cron schedule**  
   In the same service → **Settings**:
   - Find **Cron Schedule** (or **Cron**).
   - Set a crontab expression, e.g.:
     - **Every day at 8:00 Warsaw (winter):** `0 7 * * *` (7:00 UTC).
     - **Every day at 8:00 Warsaw (summer):** `0 6 * * *` (6:00 UTC).  
     Railway uses **UTC**; Warsaw is UTC+1 (winter) or UTC+2 (summer). Adjust the hour if you want a different local time.

4. **Same env vars as the web service**  
   In the **Cron service** → **Variables**, add the same variables the backend needs to scrape and write to the DB:
   - **SUPABASE_URL**
   - **SUPABASE_SERVICE_ROLE_KEY**  
   Optionally **APIFY_TOKEN** if you use it elsewhere. The Cron service does **not** need to receive the webhook (no need to expose a port). It only runs `hunter run-all`, which uses `config.example.yaml` (or your deployed config) and these env vars.

5. **No port / no web**  
   This service does not serve HTTP. It starts when the cron fires, runs `hunter run-all`, then exits. Railway will not route traffic to it.

---

## 2. Behaviour

- **Web service (existing):** Keeps serving POST /api/run and GET /api/run/status. “Odśwież oferty” still starts a run in a **background thread** with `on_demand_max_pages_auctions` (e.g. 10 pages). That run may be killed if the container stops.
- **Cron service (new):** On the schedule (e.g. daily at 7:00 UTC), Railway starts this service, runs **`hunter run-all`** (full scrape, all pages from config), writes to Supabase, then the process **exits**. Railway does not stop it early; it runs as long as the scrape needs (e.g. 15–30 minutes).

So the DB gets a **full** scrape from the Cron job on a schedule, and optionally a **quick** refresh from the button when the web run completes.

---

## 3. Check that it ran

- Railway → **Cron service** → **Deployments** or **Logs**: after the scheduled time you should see logs for Komornik and e-licytacje (list pages, upserts).
- Supabase → **listings** (and **scrape_runs** if you use it): new or updated rows after the cron time.

---

## 4. Optional: run the same command on demand

Railway does not offer “trigger this cron now” from the UI. If you want a **full** scrape on demand as well:

- Run locally: `hunter run-all` (with the same env or config as production), or  
- Temporarily run the Cron service’s start command in a one-off job (if your setup supports it), or  
- Rely on the scheduled run and use the button only for a quick refresh (fewer pages).

---

## Summary

| Goal                         | How |
|-----------------------------|-----|
| Full scrape, runs as long as needed | New Railway service, start command `hunter run-all`, Cron Schedule e.g. `0 7 * * *`, same SUPABASE_* (and optional APIFY_*) vars. |
| Quick refresh from the app  | Keep POST /api/run on the web service; use `on_demand_max_pages_auctions` (e.g. 10) so that run is shorter. |
