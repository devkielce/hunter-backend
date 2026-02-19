# Frontend: proxy for POST /api/run (Odśwież oferty)

The backend exposes **POST /api/run** and **GET /api/run/status** on Railway. The frontend must **not** call Railway directly from the browser (to avoid exposing the run secret). Instead, the frontend calls its own **Vercel API routes**, which proxy to Railway with the secret.

Scrapers run **in the background** on the backend. POST /api/run returns **202 Accepted** immediately; the frontend should then **poll GET /api/run/status** until the run is completed or failed, then refresh the listings.

---

## Backend contract (Railway)

**POST /api/run**

- **URL:** `https://hunter-backend-production-0f3d.up.railway.app/api/run` (or your current Railway URL)
- **Method:** POST
- **Headers:** **X-Run-Secret** (required if backend has a secret) — same value as `APIFY_WEBHOOK_SECRET` on Railway.
- **Body:** None required (empty body or `{}`).
- **202 Accepted:** Run started in background. Body: `{ "ok": true, "status": "started", "message": "Scrapers running in background. Poll GET /api/run/status for completion." }`. Frontend should poll **GET /api/run/status** until `status` is `completed` or `error`.
- **409 Conflict:** A run is already in progress. Body: `{ "ok": false, "error": "Run already in progress", "status": "running" }`.
- **401:** Missing or wrong X-Run-Secret.
- **500:** Backend error before starting the thread.

**GET /api/run/status**

- **URL:** `https://hunter-backend-production-0f3d.up.railway.app/api/run/status`
- **Method:** GET
- **Headers:** Same **X-Run-Secret** as POST /api/run (required if backend has a secret).
- **200 OK:** Body: `{ "ok": true, "status": "idle" | "running" | "completed" | "error", "started_at": "<iso>" | null, "finished_at": "<iso>" | null, "results": [ ... ] | null, "error": "<string>" | null }`. When `status === "completed"`, `results` is the same shape as before (per-source listings_found, listings_upserted, status, error_message). When `status === "error"`, `error` contains the message.
- **401:** Missing or wrong X-Run-Secret.
- **500:** Backend error.

---

## Vercel env required for the proxy

- **BACKEND_URL** – Railway base URL, e.g. `https://hunter-backend-production-0f3d.up.railway.app` (no trailing slash).
- **HUNTER_RUN_SECRET** – Same value as `APIFY_WEBHOOK_SECRET` on Railway.

---

## Frontend flow (Odśwież oferty)

1. User clicks **Odśwież oferty** → frontend calls **POST /api/run** (your Vercel proxy → Railway).
2. If response is **202**: show e.g. "Odświeżanie w toku..." and start **polling GET /api/run/status** every 2–3 seconds (same proxy → Railway, same **X-Run-Secret**).
3. When **GET /api/run/status** returns `status === "completed"`: refresh the listings list (re-fetch your listings from Supabase or your API) and show success. When `status === "error"`: show `error` to the user.
4. If POST /api/run returns **409**: a run is already in progress; you can show "Odświeżanie już trwa" and optionally poll status until completed.

No long timeout is needed on the proxy: POST returns immediately (202), and each GET /api/run/status is a quick request.

---

## Next.js proxy implementation

You need **two** proxy routes: one for **POST /api/run** and one for **GET /api/run/status** (e.g. `app/api/run/status/route.ts` or `pages/api/run/status.ts`). Both must send **X-Run-Secret** to Railway.

### App Router (app/api/run/route.ts)

```ts
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL;
const HUNTER_RUN_SECRET = process.env.HUNTER_RUN_SECRET;

export async function POST() {
  if (!BACKEND_URL) {
    return NextResponse.json(
      { error: "BACKEND_URL not configured" },
      { status: 500 }
    );
  }

  const url = `${BACKEND_URL.replace(/\/$/, "")}/api/run`;
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (HUNTER_RUN_SECRET) {
    headers["X-Run-Secret"] = HUNTER_RUN_SECRET;
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    console.error("Proxy /api/run failed:", e);
    return NextResponse.json(
      { error: "Backend request failed" },
      { status: 502 }
    );
  }
}
```

**GET /api/run/status (App Router: app/api/run/status/route.ts)**

```ts
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL;
const HUNTER_RUN_SECRET = process.env.HUNTER_RUN_SECRET;

export async function GET() {
  if (!BACKEND_URL) {
    return NextResponse.json({ error: "BACKEND_URL not configured" }, { status: 500 });
  }
  const url = `${BACKEND_URL.replace(/\/$/, "")}/api/run/status`;
  const headers: HeadersInit = {};
  if (HUNTER_RUN_SECRET) headers["X-Run-Secret"] = HUNTER_RUN_SECRET;
  try {
    const res = await fetch(url, { method: "GET", headers });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: "Backend request failed" }, { status: 502 });
  }
}
```

### Pages Router (pages/api/run.ts)

```ts
import type { NextApiRequest, NextApiResponse } from "next";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const BACKEND_URL = process.env.BACKEND_URL;
  const HUNTER_RUN_SECRET = process.env.HUNTER_RUN_SECRET;

  if (!BACKEND_URL) {
    return res.status(500).json({ error: "BACKEND_URL not configured" });
  }

  const url = `${BACKEND_URL.replace(/\/$/, "")}/api/run`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (HUNTER_RUN_SECRET) headers["X-Run-Secret"] = HUNTER_RUN_SECRET;

  try {
    const backendRes = await fetch(url, { method: "POST", headers, body: "{}" });
    const data = await backendRes.json().catch(() => ({}));
    res.status(backendRes.status).json(data);
  } catch (e) {
    console.error("Proxy /api/run failed:", e);
    res.status(502).json({ error: "Backend request failed" });
  }
}
```

**GET /api/run/status (Pages Router: pages/api/run/status.ts)**

```ts
import type { NextApiRequest, NextApiResponse } from "next";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const BACKEND_URL = process.env.BACKEND_URL;
  const HUNTER_RUN_SECRET = process.env.HUNTER_RUN_SECRET;
  if (!BACKEND_URL) return res.status(500).json({ error: "BACKEND_URL not configured" });
  const url = `${BACKEND_URL.replace(/\/$/, "")}/api/run/status`;
  const headers: Record<string, string> = {};
  if (HUNTER_RUN_SECRET) headers["X-Run-Secret"] = HUNTER_RUN_SECRET;
  try {
    const backendRes = await fetch(url, { method: "GET", headers });
    const data = await backendRes.json().catch(() => ({}));
    res.status(backendRes.status).json(data);
  } catch (e) {
    res.status(502).json({ error: "Backend request failed" });
  }
}
```

---

## Why it works locally but not on Railway

**config.yaml is not deployed.** It’s in `.gitignore`, so Railway only has `config.example.yaml` (placeholders) and **environment variables**. Locally you have a real `config.yaml` with Supabase and the run secret; on Railway you must provide the same via **Railway → Variables**.

**Railway checklist (required):**

| Variable | Purpose |
|----------|--------|
| **SUPABASE_URL** | Supabase project URL (same as in your local config) |
| **SUPABASE_SERVICE_ROLE_KEY** | Supabase service role key (so scrapers can upsert) |
| **APIFY_WEBHOOK_SECRET** | Run API and Apify webhook auth; frontend must send this as `X-Run-Secret` |

- If **SUPABASE_URL** or **SUPABASE_SERVICE_ROLE_KEY** are missing, scrapers may fail or upsert 0 rows.
- If **APIFY_WEBHOOK_SECRET** is set on Railway but the frontend doesn’t send the same value in **X-Run-Secret**, you get **401 Unauthorized** on POST /api/run and GET /api/run/status.

Optional: **APIFY_TOKEN** (for Apify Facebook flow). Scraping options (e.g. `max_pages_auctions`) come from `config.example.yaml` on Railway unless you add more env-based overrides.

---

## Why you get 500

- **BACKEND_URL** or **HUNTER_RUN_SECRET** missing in Vercel → proxy returns 500 or backend returns 401.
- Proxy route missing or wrong path → Vercel may return 500 or 404.
- **Backend (Railway) error:** config missing (e.g. Supabase URL/key), scraper failure, or DB error. The backend now returns 500 with a JSON body: `{ "ok": false, "error": "<message>" }`. Check the response body in the browser Network tab or in the frontend proxy (e.g. log `data.error` when status is 500). Also check Railway → service → Logs for the full traceback.
- After adding the route and env vars, **redeploy** the frontend on Vercel.

---

## 401 Unauthorized troubleshooting

A **401** with `{ "ok": false, "error": "Unauthorized" }` means the backend (Railway) did not receive a valid **X-Run-Secret** header (missing or value does not match).

Checklist:

1. **Proxy sends the header** – In your route (`app/api/run/route.ts` or `pages/api/run.ts`), the outgoing `fetch` to Railway must set `headers["X-Run-Secret"] = process.env.HUNTER_RUN_SECRET` (or equivalent). No typo in the header name; the backend expects `X-Run-Secret`.
2. **HUNTER_RUN_SECRET set on Vercel** – In Vercel → Project → Settings → Environment Variables, **HUNTER_RUN_SECRET** must be set for the environment you use (e.g. Production).
3. **Value matches Railway** – **HUNTER_RUN_SECRET** must be the **exact** same string as **APIFY_WEBHOOK_SECRET** on Railway (copy from Railway → hunter-backend service → Variables). No leading/trailing spaces.
4. **Redeploy** – Env changes apply only on the next deployment. Trigger a new deploy after adding or changing **HUNTER_RUN_SECRET**.
5. **Env scope** – If you use Preview deployments, ensure **HUNTER_RUN_SECRET** is set for the environment that serves the request (e.g. Production when opening the production URL).
