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

## 4. Date formatting (najczęstsza przyczyna hydration)

**Problem:** "External changing data without sending a snapshot" — serwer i klient formatują datę inaczej (locale, timezone), więc HTML się różni.

**Unikaj w pierwszym renderze (SSR):**
```js
// ❌ Źle — brak locale = zależne od środowiska (serwer vs przeglądarka)
new Date(listing.created_at).toLocaleDateString()

// ❌ Ryzykowne — nawet z locale serwer (Node) i klient mogą dać inny output
new Date(listing.created_at).toLocaleDateString('pl-PL', { dateStyle: 'medium' })
```

**Rozwiązania (wybierz jedno):**

1. **Format deterministyczny** (ten sam na serwerze i kliencie):
```js
// ✅ Deterministic
new Date(listing.created_at).toISOString().slice(0, 10)  // "2026-02-20"
// lub stałe opcje locale + timeZone (np. 'Europe/Warsaw')
new Date(listing.created_at).toLocaleDateString('pl-PL', { timeZone: 'Europe/Warsaw', dateStyle: 'medium' })
```

2. **Datę formatuj tylko po stronie klienta** (np. wewnątrz komponentu gated by `useMounted()`): na serwerze pokazuj placeholder (np. `"—"` lub ISO), po mount dopisz `toLocaleDateString('pl-PL', { ... })`.

Nie używaj `Date.now()` ani `Math.random()` w key ani w treści podczas pierwszego renderu.

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
