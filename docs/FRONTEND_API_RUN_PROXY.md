# Frontend: proxy for POST /api/run (Odśwież oferty)

The backend exposes **POST /api/run** on Railway. The frontend must **not** call Railway directly from the browser (to avoid exposing the run secret). Instead, the frontend calls its own **Vercel API route**, which proxies the request to Railway with the secret.

---

## Backend contract (Railway)

- **URL:** `https://hunter-backend-production-0f3d.up.railway.app/api/run` (or your current Railway URL)
- **Method:** POST
- **Headers:**
  - **X-Run-Secret:** (required if backend has a secret) Same value as `APIFY_WEBHOOK_SECRET` on Railway. Backend reads secret from config `run_api.secret` or `apify.webhook_secret` (env: `APIFY_WEBHOOK_SECRET`). If no secret is set on the backend, the header is optional.
- **Body:** None required (empty body or `{}`).
- **Success (200):** JSON body:
  ```json
  { "ok": true, "results": [
    { "source": "komornik", "listings_found": 1, "listings_upserted": 1, "status": "success", "error_message": null },
    { "source": "e_licytacje", ... }
  ]}
  ```
- **401:** Missing or wrong `X-Run-Secret`.
- **500:** Backend error (e.g. Supabase or scraper failure).

---

## Vercel env required for the proxy

- **BACKEND_URL** – Railway base URL, e.g. `https://hunter-backend-production-0f3d.up.railway.app` (no trailing slash).
- **HUNTER_RUN_SECRET** – Same value as `APIFY_WEBHOOK_SECRET` on Railway.

---

## Next.js proxy implementation

The frontend currently does `fetch("/api/run", { method: "POST" })`. That request hits **Vercel**, so you must have a route that proxies to Railway.

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

---

## Why you get 500

- **BACKEND_URL** or **HUNTER_RUN_SECRET** missing in Vercel → proxy returns 500 or backend returns 401.
- Proxy route missing or wrong path → Vercel may return 500 or 404.
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
