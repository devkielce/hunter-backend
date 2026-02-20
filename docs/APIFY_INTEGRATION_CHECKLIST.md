# Apify integration checklist (Facebook Groups Scraper → Hunter backend)

Use this from the Apify **Integrations** screen (HTTP request on “Run succeeded”).

---

## 1. URL ✓

- **URL:** `https://hunter-backend-production-0f3d.up.railway.app/webhook/apify`
- Method: **POST** (Apify HTTP request integrations use POST by default).
- You already have this; leave as is.

---

## 2. Headers

- **Header name:** `x-apify-webhook-secret` (or `X-Apify-Webhook-Secret`)
- **Value:** Must be **exactly** the same as on the backend.

**On the backend (Railway):**

- Either in `config.yaml`: `apify.webhook_secret: "YOUR_SECRET"`
- Or env var: `APIFY_WEBHOOK_SECRET=YOUR_SECRET`

Copy that same value into the Apify integration **Headers** template, e.g.:

```json
{
  "Content-Type": "application/json",
  "x-apify-webhook-secret": "YOUR_SECRET_HERE"
}
```

If you don’t set `webhook_secret` on the backend, you can leave the header out (no auth). For production, set a secret on both sides.

---

## 3. Payload (body) – dataset ID

The backend needs the **dataset ID** of the run so it can fetch the scraped items. It looks for:

1. Top-level **`datasetId`** (string), or  
2. **`resource.defaultDatasetId`** (string inside `resource`).

Your current payload:

```json
{
  "userId": {{userId}},
  "createdAt": {{createdAt}},
  "eventType": {{eventType}},
  "eventData": {{eventData}},
  "resource": {{resource}}
}
```

- If Apify’s **`{{resource}}`** is the **Run** object, it usually has **`defaultDatasetId`**. In that case the backend will read `resource.defaultDatasetId` and you don’t need to change anything.
- If the backend responds with **400** and `"Missing datasetId or resource.defaultDatasetId"`, then `resource` doesn’t contain the dataset ID. Fix it by adding it explicitly.

**Option A – Add top-level `datasetId` (recommended if 400 happens):**

In the Payload template, add a line so the body includes the run’s default dataset ID. In Apify’s integration template you can often use the run’s default dataset ID, for example:

```json
{
  "userId": {{userId}},
  "createdAt": {{createdAt}},
  "eventType": {{eventType}},
  "eventData": {{eventData}},
  "resource": {{resource}},
  "datasetId": "{{resource.defaultDatasetId}}"
}
```

(If your Apify UI uses a different variable for the run’s default dataset ID, use that instead of `{{resource.defaultDatasetId}}`.)

**Option B – Keep only `resource`:**

If `{{resource}}` already includes `defaultDatasetId`, your current payload is enough; no change.

---

## 4. Content-Type

- The backend expects JSON: `Content-Type: application/json`.
- Apify HTTP request integrations usually send JSON by default; if you have a “Body” or “Payload” set to the JSON above, you’re good. If there’s a “Content-Type” header field, set it to `application/json`.

---

## 5. Test the flow

1. **Backend:** Ensure Railway has:
   - `APIFY_TOKEN` (or `apify.token` in config) so the backend can call Apify’s API to fetch the dataset.
   - `apify.webhook_secret` / `APIFY_WEBHOOK_SECRET` if you use the secret header.

2. **Apify:** Run the Facebook Groups Scraper once (e.g. “Run” on the actor).

3. When the run **succeeds**, Apify will POST to your webhook. Then:
   - **200 + JSON** with `listings_found` and `listings_upserted` → backend received the dataset ID, fetched items, and upserted; check your app/Supabase for `source=facebook` listings.
   - **400 "Missing datasetId or resource.defaultDatasetId"** → adjust the payload as in step 3 (add `datasetId` or fix `resource`).
   - **401 Unauthorized** → `x-apify-webhook-secret` value doesn’t match the backend’s `apify.webhook_secret` / `APIFY_WEBHOOK_SECRET`.

---

## 6. Optional: schedule

- In Apify: **Schedules** tab for this actor → create a schedule (e.g. daily) so runs start automatically and the webhook is called after each successful run.
- The backend does not start Apify runs; it only reacts when Apify calls `/webhook/apify` with a dataset ID.

---

## Quick reference (backend expectations)

| Item              | Backend expectation                                  |
|-------------------|------------------------------------------------------|
| URL               | `POST /webhook/apify`                                |
| Header (optional) | `x-apify-webhook-secret` = same as in config/env     |
| Body              | JSON with `datasetId` or `resource.defaultDatasetId` |
| Response 200      | `{"ok": true, "listings_found": N, "listings_upserted": M}` |
