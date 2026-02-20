# Data in DB but not showing in the frontend app

The backend upserted listings (e.g. 857 from Komornik) and you see them in the Supabase dashboard, but the Next.js app shows no (or fewer) listings.

---

## 1. Different Supabase project (most common)

Backend and frontend must use the **same Supabase project**.

| App      | Where URL is set              | What to check |
|----------|--------------------------------|---------------|
| Backend  | Railway: `SUPABASE_URL` (or `config.yaml` → `supabase.url`) | Copy the **Project URL** from Supabase dashboard (e.g. `https://xxxx.supabase.co`) |
| Frontend | Vercel/local: `NEXT_PUBLIC_SUPABASE_URL` (and anon key and/or `SUPABASE_SERVICE_ROLE_KEY` for server routes) | Must be **exactly** the same URL as the backend |

**Check:** In Supabase dashboard → **Settings → API**: compare **Project URL**. Then in Railway (backend) and Vercel (frontend) env vars, confirm both point to that URL. If the frontend uses a different project (e.g. old or staging), it will read a different `listings` table and show no data.

---

## 2. Frontend filters hiding the data

The frontend might filter by:

- **Source** – e.g. only showing `source = 'facebook'` or `source = 'e_licytacje'`, and not including `komornik`.
- **Status** – e.g. only `status = 'new'` (your data should have `status = 'new'` by default).
- **Date / “NEW today”** – e.g. only listings where `created_at` is today; older upserts would be excluded.

**Check:** In the frontend code, find where it queries Supabase (e.g. `.from('listings').select(...)`). Look for `.eq('source', ...)`, `.eq('status', ...)`, or filters on `created_at`. Ensure `komornik` (and other sources you use) are not excluded, and that default status/date logic matches your data.

---

## 3. Wrong table or RLS

- **Table:** Frontend must query the `listings` table (same as backend). Typo or a different table name would show no rows.
- **RLS:** The taskmaster schema (`supabase_schema.sql`) enables RLS with a policy **“Allow all on listings”** (`USING (true) WITH CHECK (true)`). It depends how the frontend connects. **Service role** (e.g. `SUPABASE_SERVICE_ROLE_KEY` in a Next.js server/API route): RLS is bypassed, so "0 rows from RLS" does not apply. **Anon key** (client-side): RLS applies; if you never ran the schema or added stricter policies, the anon key might see 0 rows.

**Check:** In Supabase → **Table Editor** → `listings`: confirm rows exist and note the **Project** (top of dashboard). In **Authentication → Policies** for `listings`, confirm there is a permissive policy (e.g. “Allow all on listings”) if the frontend uses the anon key; when using the service role, RLS is bypassed.

---

## 4. Quick verification

1. **Supabase SQL editor** (same project as backend):  
   `SELECT COUNT(*), source FROM listings GROUP BY source;`  
   You should see `komornik` (and others) with counts.

2. **Frontend env:**  
   Temporarily log or print `process.env.NEXT_PUBLIC_SUPABASE_URL` (or your frontend Supabase URL) in the app or in a server route. Confirm it matches the backend’s Supabase project URL.

3. **Frontend query:**  
   In the frontend, run a minimal query (e.g. `.from('listings').select('id, title, source').limit(10)`) with no filters and log the result. If you get 0 rows while the dashboard shows rows, it’s either the wrong project or RLS.

---

## Summary

| Cause              | What to do |
|--------------------|------------|
| Different project  | Set frontend `NEXT_PUBLIC_SUPABASE_URL` (and keys) to the **same** Supabase project as backend `SUPABASE_URL`. |
| Frontend filters   | Include `komornik` (and other sources) in the source filter; relax or check status/date filters. |
| Wrong table / RLS  | Query `listings`; apply `supabase_schema.sql` so RLS allows read (e.g. “Allow all on listings”). |

After aligning the project and filters, the app will show the same listings you see in the DB.
