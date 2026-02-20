# Frontend hydration edge-case checklist (App Router)

After fixing obvious hydration issues (e.g. `useMounted()` for time-based UI), if **#418** / **#423** still appear intermittently, check these App Router edge cases.

---

## 1. Server → client prop shape mismatch

- A prop `undefined` on server but defined on client, or different array/object shape, can break hydration.
- **Safer:** Normalize so shape is identical (e.g. `data={maybeUndefined ?? null}`).

---

## 2. Mutating server data in a client component

- **Avoid:** `props.items.sort(...)` — mutating the array from the server can cause mismatch.
- **Use:** `const sorted = useMemo(() => [...props.items].sort(...), [props.items])`.

---

## 3. Unstable `key` in lists

- **Avoid:** `key={i}` (index) — order changes can break hydration.
- **Use:** Stable key, e.g. `key={item.id}`.

---

## 4. Time/locale in helpers during initial render

- Helpers that use `new Date()`, `Date.now()`, `toLocale*`, `Intl.*` must only run **after** `mounted` (or inside client-only code).
- Search for `new Date(`, `Date.now(`, `toLocale`, `Intl.` and ensure none run during first render.

---

## 5. Server component revalidation timing

- `revalidate = 0` or dynamic fetches can make the server snapshot differ from the client.
- To test: temporarily use `export const dynamic = "force-static"`; if the error goes away, it’s revalidation/timing.

---

## 6. StrictMode (dev only)

- In dev, StrictMode double-renders. Mutations during render can show hydration errors that don’t appear in prod.

---

## 7. Client component importing server-only code

- If a **client** component (or a helper it imports) pulls in a **server-only** module (e.g. `next/headers`, `cookies()`), the boundary breaks and hydration can fail.
- Example: client Card → `@/lib/utils` → `import { cookies } from "next/headers"` ❌

---

## Recommended setup (listings dashboard)

- Server-rendered dashboard list; client cards.
- `useMounted()` (or similar) gating time-based UI.
- No `typeof window` in render; stable placeholder during hydration.
- Stable keys (`item.id`), no mutation of server props, normalized prop shape.

---

## Audit

To do a full hydration-risk audit, provide:

- `DashboardPage` (server component)
- One `Card` (client component)
- `useMounted()` (or equivalent) implementation
