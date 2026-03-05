# Pobieranie zdjęć podczas scrapowania

Opcjonalnie backend może **pobierać zdjęcia** z URL-i ofert i **wgrywać je do Supabase Storage**. Wtedy w `listings.images` zapisywane są adresy z Twojego bucketu zamiast z OLX/Gratka/Facebook – frontend może wyświetlać obrazy bez konfiguracji `remotePatterns` dla zewnętrznych domen i nie jest uzależniony od dostępności zdjęć u źródła.

## Włączenie

W `config.yaml` (sekcja `scraping`):

```yaml
scraping:
  download_images: true
  # Opcjonalnie:
  download_images_max_per_listing: 5   # domyślnie 5
  download_images_timeout_seconds: 15  # domyślnie 15
```

W Supabase (sekcja `supabase`) możesz ustawić nazwę bucketu (domyślnie `listing-images`):

```yaml
supabase:
  storage_bucket: "listing-images"
```

## Bucket w Supabase

**Opcja A – SQL:** Uruchom w Supabase SQL Editor plik `supabase_migration_storage_listing_images.sql` – tworzy bucket `listing-images` (public).

**Opcja B – ręcznie:** W **Supabase Dashboard** → **Storage** → New bucket: nazwa **`listing-images`**, włącz **Public bucket**.

Backend wgrywa pliki pod ścieżką `listings/{source}_{hash}/{indeks}.{ext}` (np. `listings/olx_a1b2c3d4e5f6/0.jpg`).

## Zachowanie

- Działa dla **wszystkich scraperów** (run.py) oraz dla **Facebook (Apify)** (process_apify_dataset).
- Dla każdej oferty pobierane są co najwyżej **N** pierwszych zdjęć (N = `download_images_max_per_listing`).
- Między żądaniami GET jest stosowane opóźnienie z `scraping.httpx_delay_seconds`.
- Jeśli pobranie lub upload się nie uda, dla tego obrazu pozostawiany jest oryginalny URL (obecnie lista `images` jest zastępowana tylko **udanymi** URL-ami Storage; nieudane są pomijane).
- W `raw_data` zapisywane jest `images_uploaded: true`, gdy choć jedno zdjęcie zostało wgrane.

## Frontend

Bez zmian: nadal odczytujesz `listing.images` (np. `listing.images?.[0]`) i podajesz do `<Image src={...} />`. Gdy `download_images: true`, te URL-e będą z Twojej domeny Supabase Storage – możesz dodać ją do `remotePatterns` w Next.js albo użyć zwykłego `<img>`, jeśli bucket jest publiczny.
