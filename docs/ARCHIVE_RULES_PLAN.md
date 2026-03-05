# Reguły archiwizacji ofert

**Zaimplementowano.** Backend stosuje dwie reguły: (1) niewidziane w ostatnich 5 runach, (2) oferta starsza niż 2 miesiące (po `auction_date` dla Komornik, e-licytacje, AMW, Facebook).

---

## Dlaczego listy z Komornika bywają masowo archiwizowane?

Obecnie archiwizacja „5 runów” oznacza: oferty **niewidziane w ostatnich 5 udanych runach** (porównanie `last_seen_at` z datą 5. runu wstecz).

Jeśli scraper Komornika **zwraca 0 ofert** przez 5 udanych runów z rzędu (zmiana listy, region, błąd strony):
- żadna oferta nie jest upsertowana,
- nikt nie dostaje zaktualizowanego `last_seen_at`,
- cutoff = `started_at` 5. runu wstecz,
- **wszystkie** oferty mają `last_seen_at` starsze niż cutoff (albo NULL) → **wszystkie są archiwizowane**.

Czyli masowa archiwizacja zwykle oznacza: **przez 5 runów scraper w ogóle nie zwracał tych ofert** (0 wyników). Warto sprawdzić w logach / `scrape_runs` wartości `listings_found` i `listings_upserted` dla komornik.

---

## Reguły (zaimplementowane)

| Warunek | Działanie |
|--------|-----------|
| Strona się otwiera **i** można zczytać te same dane co ostatnio | **Nie archiwizuj** (upsert ustawia `last_seen_at`) |
| **Nie można** zczytać danych **5 razy z rzędu** (scraper nie zwraca oferty) | **Archiwizuj** |
| Można zczytać dane, **ale** oferta **starsza niż 2 miesiące** (po `auction_date` / dacie posta) | **Archiwizuj** (komornik, e_licytacje, amw, **Facebook**) |

**Facebook:** data posta z Apify (np. `date_posted`, `postedAt`, `time`, `created_time`) jest zapisywana w `auction_date`; po każdym webhooku wywoływane jest `archive_listings_older_than("facebook", ...)` — ta sama reguła co dla pozostałych źródeł.

---

## Implementacja

- **Krok 1 (po każdym udanym runie):** `archive_listings_not_seen_in_last_n_runs(client, source, n=5)` — jak dotąd.
- **Krok 2 (dla komornik, e_licytacje, amw, facebook):** `archive_listings_older_than(client, source, interval="2 months")` — RPC ustawia `removed_from_source_at` dla listingów z `auction_date < now() - interval`. Dla Facebooka `auction_date` = data posta z Apify (wyciągana w `normalize_facebook_item`); po `process_apify_dataset` wywoływane jest archiwum po wieku.

**Config:** `scraping.archive_older_than_months: 2` (domyślnie 2). Backend przekazuje `f"{months} months"` do RPC.

**Migracje:** `supabase_migration_source_archive.sql` (kolumny + RPC „5 runów”), potem `supabase_migration_archive_by_age.sql` (RPC „starsze niż N miesięcy”). W RPC `archive_listings_older_than` kolejność parametrów to `(p_interval, p_source)` tak, aby schema cache PostgREST poprawnie rozpoznawał funkcję przy wywołaniu z Pythona (parametry przekazywane po nazwie).

Szczegóły: `docs/DOCUMENTATION.md` sekcja 6.
