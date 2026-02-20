# Frontend render snippet (listings)

Snippet for rendering a single listing in the Next.js dashboard. Uses the same field names as the backend/Supabase (snake_case). Handles null `auction_date` and formats `price_pln` (grosze → PLN).

---

## Type (TypeScript)

```ts
// listing type aligned with Supabase / backend
type Listing = {
  id: string;
  title: string;
  description: string | null;
  price_pln: number | null;   // grosze
  location: string | null;
  city: string | null;
  source: string;
  source_url: string;
  auction_date: string | null;  // ISO 8601
  created_at: string;
  updated_at: string;
  images: string[];
  status: string;
  region?: string;  // optional, from Komornik
};
```

---

## Select query (Supabase)

Include the fields you render so dates and price are present:

```ts
const { data: listings } = await supabase
  .from('listings')
  .select('id, title, description, price_pln, location, city, source, source_url, auction_date, created_at, updated_at, images, status, region')
  .order('created_at', { ascending: false });
```

---

## Listing card component (React)

```tsx
function ListingCard({ listing }: { listing: Listing }) {
  // Price: backend stores grosze
  const pricePln = listing.price_pln != null ? (listing.price_pln / 100).toFixed(0) : null;

  // Date: show auction_date if set, else created_at (per DATE_NOT_RENDERING.md).
  // Use || so empty string from DB falls back to created_at; backend normalizes "" → null.
  const displayDate = listing.auction_date || listing.created_at;
  const dateLabel = listing.auction_date && String(listing.auction_date).trim() ? 'Licytacja' : 'Dodano';
  const dateStr = displayDate
    ? new Date(displayDate).toLocaleDateString('pl-PL', { dateStyle: 'medium' })
    : null;

  return (
    <article className="listing-card">
      {listing.images?.[0] && (
        <img src={listing.images[0]} alt="" className="listing-card__img" />
      )}
      <div className="listing-card__body">
        <h3 className="listing-card__title">
          <a href={listing.source_url} target="_blank" rel="noopener noreferrer">
            {listing.title}
          </a>
        </h3>
        {listing.description && (
          <p className="listing-card__description">{listing.description}</p>
        )}
        <div className="listing-card__meta">
          {pricePln != null && <span>{pricePln} zł</span>}
          {listing.location && <span>{listing.location}</span>}
          {listing.region && <span>{listing.region}</span>}
          <span>{listing.source}</span>
        </div>
        {dateStr && (
          <div className="listing-card__date">
            {dateLabel}: {dateStr}
          </div>
        )}
        {listing.status && (
          <span className="listing-card__status">{listing.status}</span>
        )}
      </div>
    </article>
  );
}
```

---

## Minimal row (table or list)

```tsx
<tr>
  <td>{listing.title}</td>
  <td>{listing.price_pln != null ? (listing.price_pln / 100) + ' zł' : '—'}</td>
  <td>{listing.source}</td>
  <td>
    {(listing.auction_date || listing.created_at)
      ? new Date(listing.auction_date || listing.created_at).toLocaleDateString('pl-PL')
      : '—'}
  </td>
  <td><a href={listing.source_url} target="_blank" rel="noopener noreferrer">Link</a></td>
</tr>
```

---

## Notes

- Use **snake_case** from the API: `listing.auction_date`, `listing.created_at`, `listing.price_pln`.
- **price_pln** is in grosze: divide by 100 for PLN.
- **auction_date** is often `null`; use **created_at** as fallback so something always renders.
- **images** is `string[]` (array of URLs).
