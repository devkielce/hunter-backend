# Date from listings not rendering in the frontend (no errors)

The backend stores date fields in Supabase, but the frontend shows nothing for them. No console or runtime errors.

---

## What’s in the DB

| Column        | Type        | Who sets it        | Often null? |
|---------------|-------------|--------------------|-------------|
| **auction_date** | TIMESTAMPTZ | Backend (scrapers) | **Yes** – set only when the scraper parses a date from the detail page (e.g. “Termin licytacji”). Many rows have `null`. |
| **created_at**   | TIMESTAMPTZ | DB default `now()` | No         |
| **updated_at**   | TIMESTAMPTZ | DB trigger         | No         |

Supabase returns these as **ISO 8601 strings** (e.g. `"2024-03-15T10:00:00.000Z"`), not Date objects.

---

## Why it might not render (no errors)

### 1. Field not selected

If the frontend does:

```ts
.from('listings').select('id, title, description, price_pln, location, source')
```

then `auction_date`, `created_at`, and `updated_at` are **not** in the response. The UI has nothing to show.

**Fix:** Include the columns you need, e.g. `select('*')` or add `auction_date, created_at, updated_at` to the select list.

---

### 2. Wrong property name

Backend and DB use **snake_case**: `auction_date`, `created_at`, `updated_at`.

If the frontend uses camelCase (e.g. `listing.auctionDate`, `listing.createdAt`) and the API returns snake_case, the value is `undefined` and nothing renders.

**Fix:** Use the same keys as the API: `listing.auction_date`, `listing.created_at`, `listing.updated_at`. Or map the response to camelCase and use that everywhere.

---

### 3. `auction_date` is null and not handled

Many listings have **`auction_date: null`** (scraper couldn’t find/parse the date). If the component does:

```tsx
{listing.auction_date.toLocaleDateString()}
// or
{new Date(listing.auction_date).toLocaleDateString()}
```

then for `null` you get a runtime error **or** “Invalid Date” / blank depending on framework. In React, sometimes it just renders nothing.

**Fix:** Guard on null/undefined before formatting:

```tsx
{listing.auction_date
  ? new Date(listing.auction_date).toLocaleDateString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  : '–' /* or "Brak daty" */}
```

Same idea for `created_at` / `updated_at` if they can ever be missing.

---

### 4. Date is a string and not parsed

Supabase returns dates as **strings**. If you pass that string to something that expects a Date or a number (e.g. a countdown library), it might fail silently or show nothing.

**Fix:** Parse before use: `new Date(listing.auction_date)` (handles ISO string and null → Invalid Date; still guard for null if you don’t want to show “Invalid Date”).

---

### 5. Conditional render hides the block

The date might only render when e.g. `source === 'komornik'` or `listing.auction_date`. If the condition is wrong or the data doesn’t match, the whole date block is skipped.

**Fix:** Check the condition and the data (e.g. `source` value, whether `auction_date` is present). Ease the condition temporarily to see if the date appears.

---

### 6. Normalization turns `undefined` into the string `"undefined"` (silent)

If you normalize Supabase rows with something like:

```ts
created_at: String(row.created_at),
updated_at: String(row.updated_at),
```

then when `row.created_at` or `row.updated_at` is **undefined** (e.g. RLS, typo, column missing from select, or row created before column existed), `String(undefined)` becomes the **literal string** `"undefined"`. Then:

- `new Date("undefined")` → **Invalid Date**
- `isNaN(d.getTime()) === true` → your fallback sets `dateStr = null` → nothing renders. No error, no crash.

**Fix:** Never blindly stringify; guard on null/undefined:

```ts
created_at: row.created_at != null ? String(row.created_at) : null,
updated_at: row.updated_at != null ? String(row.updated_at) : null,
```

And use a **defensive `normalizeListing`** for all fields (see [FRONTEND_RENDER_SNIPPET.md](./FRONTEND_RENDER_SNIPPET.md#normalize-listing-defensive)). If dates still don't render after that, log the raw row (`console.log("RAW ROW:", row)`) to confirm what Supabase actually returned.

---

## How to find the bug

1. **Supabase Table Editor**  
   Open `listings`, pick a row. Check whether `auction_date`, `created_at`, `updated_at` have values. If `auction_date` is often null, the UI must handle null.

2. **Network tab**  
   Find the request that loads listings (e.g. to Supabase or your API). Inspect the JSON: are `auction_date`, `created_at`, `updated_at` present and what type (string vs null)?

3. **Log the listing in the component**  
   `console.log(listing)` or `console.log({ auction_date: listing?.auction_date, created_at: listing?.created_at })`. Confirm the keys and values where you render.

4. **Component that shows the date**  
   Open the file that renders a row/card. See which property is used (e.g. `listing.auction_date` vs `listing.auctionDate`), whether it’s in the select, and whether null is handled.

5. **SQL in Supabase**  
   Run:  
   `SELECT id, auction_date, created_at, updated_at FROM listings LIMIT 5;`  
   See how many rows have non-null `auction_date` vs null. That tells you if “no date” is a data issue or a frontend issue.

---

## Summary

| Cause              | What to do |
|--------------------|------------|
| Column not in select | Add `auction_date`, `created_at`, `updated_at` to the Supabase `.select(...)`. |
| Wrong key (camelCase) | Use `auction_date` / `created_at` / `updated_at` or map from API to camelCase. |
| null not handled   | Check for null/undefined before formatting; show “–” or “Brak daty” when missing. |
| String not parsed  | Use `new Date(listing.auction_date)` before formatting or passing to a library. |
| Condition too strict | Relax or fix the condition that decides when to show the date. |
| Normalization: `String(undefined)` → `"undefined"` | Use `row.created_at != null ? String(row.created_at) : null` (and same for `updated_at`). Use defensive `normalizeListing`. |

Checking the API response (Network tab) and the exact property used in the component usually pinpoints the issue even when there are no errors.

---

## Resolution (frontend): always show at least one date

**Cause:** The card only rendered a date when `listing.auction_date` was set. For many listings (e.g. Komornik) `auction_date` is null in the DB, so nothing was shown. `created_at` existed but wasn’t displayed as text.

**Fix applied in the frontend:**

- If **`auction_date`** is set → show **"Licytacja: …"** with countdown and formatted date.
- If **`auction_date`** is null/empty → show **"Dodano: …"** using **`created_at`** so the user always sees at least one date.

Use a defensive **`formatDate()`** (e.g. `toLocaleString("pl-PL")` with a fallback to **"—"** for invalid/missing values) so "Invalid Date" never appears.

To have **"Licytacja"** show for more listings (e.g. Komornik), the **backend** must populate **`auction_date`** when upserting (scraper must find and parse the auction date on the detail page). The frontend will display it as soon as it’s present.
