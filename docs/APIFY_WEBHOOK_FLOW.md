# How and when the Apify (Facebook) flow runs

## Who triggers what

- **Hunter-backend does not start the Apify actor.** The Facebook scraper **actor** (run) is started **in Apify** – by a schedule or manually.
- **Apify calls the backend** when that actor run **finishes**, via a webhook you configure in Apify.
- **The backend then calls Apify** only to **fetch** the dataset (list of scraped posts) and then filters, normalizes, and upserts to Supabase.

So there are two “calls”:

1. **Apify → your backend** (webhook)
2. **Your backend → Apify API** (fetch dataset items)

---

## 1. When is the Apify actor (Facebook scrape) triggered?

**In the Apify Console**, for the actor that scrapes Facebook:

- **Schedule:** In the actor’s **Schedules** tab you can set a cron (e.g. daily at 9:00). When the schedule fires, Apify starts a new run. That’s the typical “when” for automatic runs.
- **Manual:** You can click **Run** in the Apify Console to start a run anytime.

Hunter-backend has no API to “start an Apify run”. Triggering the run is entirely in Apify (schedule or manual).

---

## 2. When does the backend get called (webhook)?

**When the Apify actor run completes**, Apify sends an HTTP request to the **Webhook URL** you configured for that actor.

- **Where to set it:** In Apify → your actor (or task) → **Settings** / **Webhooks** (or **Integrations**). Set the webhook URL to your backend, e.g.  
  `https://hunter-backend-production-xxxx.up.railway.app/webhook/apify`
- **Method:** POST  
- **Body:** JSON with `datasetId` or `resource.defaultDatasetId` (the dataset ID of the run’s output).  
- **Optional header:** `x-apify-webhook-secret` with the same value as `apify.webhook_secret` in your config (or `APIFY_WEBHOOK_SECRET` on Railway).

So the “Apify call” to your app happens **every time an Apify run for that actor finishes** and the webhook is configured.

---

## 3. What does the backend do when the webhook is called?

1. Verifies `x-apify-webhook-secret` (if you set `apify.webhook_secret`).
2. Reads `datasetId` (or `resource.defaultDatasetId`) from the JSON body.
3. Calls **Apify API**: `GET https://api.apify.com/v2/datasets/{dataset_id}/items?token=...` (using `apify.token` or `APIFY_TOKEN`).
4. Filters items by sales keywords (sprzedaż, cena, nieruchomość, mieszkanie, etc.).
5. Normalizes to the shared listing schema and **upserts** to Supabase (`listings` table, `source=facebook`).
6. Returns 200 with `listings_found` and `listings_upserted`.

So the backend **calls Apify** only in step 3, to download the dataset. It does not call Apify to start or schedule the actor.

---

## Summary

| Step | Who | When |
|------|-----|------|
| Start Facebook scrape | **You / Apify schedule** | In Apify: schedule or “Run” |
| Apify run finishes | Apify | After the actor run completes |
| Apify → backend | **Apify** | POST /webhook/apify with dataset ID |
| Backend → Apify | **Backend** | GET dataset items (to process and save to Supabase) |

To get Facebook listings into your app: ensure the Apify actor has a **schedule** (or run it manually), and that its **webhook URL** points at your deployed backend’s `/webhook/apify`.
