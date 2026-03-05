# Filtry: scraper vs aplikacja

## Ustalenia

### Scraper (backend)
- **Pobieramy wszystko** – bez filtra regionu w scraperze (Komornik, e-licytacje, AMW).
- **Cel:** maksymalna liczba ofert **z ceną** w bazie. Cena jest kluczowa.
- Filtry inteligentne (np. AI) – później; na razie MVP bez AI.

### Aplikacja (frontend / zapytania do bazy)
- **MVP (na razie bez AI):**
  - **Cena:** pokazywać tylko oferty z ceną (`price_pln IS NOT NULL`).
  - **Region:** filtr **mazowieckie** – np. `region ILIKE '%mazowieckie%'` lub pole wyboru województwa.
- **Później:** filtry inteligentne (jakość oferty, dopasowanie do użytkownika); ewentualnie model AI (OpenAI); na razie nie w scope.

### Podsumowanie
| Gdzie      | Co robimy teraz |
|-----------|------------------|
| Scraper   | Leci wszystko, bez filtra regionu. |
| Aplikacja | Filtry: ma cenę + mazowieckie (MVP, bez AI). |
| Przyszłość| Filtry inteligentne / AI w appce. |

### Komornik (licytacje.komornik.pl)
- Strona listy jest renderowana w JavaScript (Vue/Nuxt). Scraper najpierw próbuje httpx; jeśli 0 linków, używa **Playwright** do załadowania listy, potem pobiera szczegóły ofert przez httpx.
- Config `komornik_region` / `e_licytacje_region` nie jest używany – scrapers zawsze pobierają wszystkie regiony.
