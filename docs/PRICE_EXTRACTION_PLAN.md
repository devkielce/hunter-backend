# Plan implementacji: zbieranie cen (i metrażu)

**Zaimplementowano (Faza 1–2, Faza 4):** rozszerzony parser ceny, fallback z pełnego tekstu (Komornik, e-licytacje, AMW), follow-link dla Facebooka, config `follow_link_for_price` / `follow_link_domains`. **Wszystkie scrapery:** gdy na liście brak ceny (`price_pln` = null), w `run.py` wykonywany jest fallback – pobieranie strony szczegółowej (`source_url`) i wyciągnięcie ceny z HTML (regex); dotyczy AMW, Komornik, e-licytacje (Facebook dodatkowo ma follow-link do URL z treści posta). **Facebook:** filtr „tylko nieruchomości” (grupy mieszane → tylko oferty nieruchomości; szczegóły: `docs/FACEBOOK_REAL_ESTATE_FILTER.md`). **Tytuł (jedno zdanie):** moduł `title_extractor.py` – ekstrakcja bez AI (typ + pokoje + m² + kondygnacje) → np. „Mieszkanie 2-pokojowe, 45 m²”; używane w Facebook, AMW, Komornik, e-licytacje. **Metraż (Faza 4):** ekstrakcja metrażu z opisu (`extract_surface_m2` z title_extractor), zapis w `raw_data.surface_m2` we wszystkich źródłach (Facebook, AMW, Komornik, e-licytacje); frontend może czytać `listing.raw_data?.surface_m2`. Kolumna `surface_m2` w DB pozostaje opcjonalna (migracja).

Cel: zamiast „CENA DO USTALENIA” na każdym ogłoszeniu — wyciągać realne ceny ze stron (i ewentualnie z linków). Dokument zawiera plan backendu oraz **co frontend ma wiedzieć**.

---

## 1. Plan implementacji (backend)

### Faza 1: Lepsze wyciąganie ceny z bieżącej strony

1. **Sprawdzić w każdym scraperze**, gdzie dziś szukana jest cena (selektory w `_parse_detail_page` / `_parse_detail` / `_parse_list_page`).
2. **Zbadać żywy HTML** każdego źródła (DevTools): w jakim tagu/klasie jest cena; czy jest w `title` / `description`.
3. **Dodać/rozszerzyć selektory** dla Komornika, e-licytacje, AMW (np. `[data-cy='price']`, `.cena-glowna` — według faktycznego HTML).
4. **Fallback:** jeśli selektory nic nie zwrócą — przeszukać **cały tekst strony** (lub `title` + `description`) **regexem** i przekazać znaleziony fragment do `price_pln_from_text()`.
5. W **`price_parser.py`** dodać do `NO_PRICE_PHRASES` m.in. **„cena do ustalenia”**, „do ustalenia”, żeby takie oferty nadal miały `price_pln = null` i na frontendzie pokazywały „CENA DO USTALENIA”.

**Efekt:** W ofertach, gdzie cena jest na tej samej stronie (nawet w innym miejscu HTML), zacznie się zapisywać `price_pln`.

---

### Faza 2: Cena pod linkiem (gdy na stronie A brak ceny)

1. **Warunek:** Szukać linku **tylko gdy** po Fazie 1 `price_pln` nadal `None`.
2. **Wyciąganie linku ze strony A:**  
   Szukać w HTML `<a href="...">`:  
   - link do **tego samego domeny** (np. „pełna oferta”, „szczegóły”), albo  
   - link **zewnętrzny** do znanego portalu (np. arcabinvestments.com, otodom.pl, olx.pl).  
   Ograniczyć do 1–2 linków na ofertę; można filtrować po tekście („Zobacz”, „Pełna oferta”, „Szczegóły”).
3. **Pobranie strony B:** GET na wybrany URL (timeout np. 10 s).
4. **Parsowanie ceny na B:**  
   - Jeśli B to **znany portal** — dedykowany parser (selektory dla ceny).  
   - Jeśli B **nieznana** — heurystyka: regex po „X zł”, „X PLN” w tekście, przekazać do `price_pln_from_text()`.
5. **Gdzie w kodzie:** np. moduł `hunter/price_fallback.py` z funkcją `try_follow_link_for_price(soup, page_url, client, delay) → Optional[int]`; w każdym scraperze po parsowaniu, gdy `price_pln is None`, wywołać tę funkcję i ewentualnie ustawić `price_pln` oraz w `raw_data`: `price_from_followed_link: true`, `followed_price_url: "..."`.
6. **Config:** opcjonalnie `scraping.follow_link_for_price: true/false`, `scraping.follow_link_domains: [arcabinvestments.com, otodom.pl, ...]`.

**Efekt:** Część ofert (np. Facebook z linkiem do arcabinvestments.com) dostanie cenę z drugiej strony.

---

### Faza 3: Konkretne źródła (zapis struktury stron)

- **Facebook:** W poście często brak ceny; jest link typu „Pełna oferta: https://arcabinvestments.com/oferta/...”. Gdy brak ceny → wyciągnąć pierwszy taki link → GET → parser/regex po stronie docelowej. Metraż w poście: „54,55 m²” — regex.
- **AMW (strona szczegółowa):** Sekcja „Szczegóły oferty” → np. „Miesięczny czynsz netto: 6 000 zł”. Powierzchnia: „użytkowa: 144,55 m²”. Parser: szukać bloku „Szczegóły oferty”, w nim wzorce „X zł”; osobno „użytkowa: X m²”.
- **Komornik (strona szczegółowa):** Treść w `#Preview` / `.schema-preview`. Cena w tekście: „cena wywołania … wynosi 61 500,00 zł”, „Suma oszacowania wynosi 82 000,00 zł”. Parser: `get_text()` z kontenera → regex → `price_pln_from_text()`.

---

### Faza 4: Metraż ✅ Zaimplementowano

1. **Parser metrażu:** Wykorzystany `extract_surface_m2` z `title_extractor.py` (regex na „X m²”, „pow. X”, „powierzchnia X”).
2. **Zapis:** W `raw_data.surface_m2` we wszystkich źródłach (Facebook, AMW, Komornik, e-licytacje). Kolumna `surface_m2` w DB opcjonalna (migracja).
3. **Frontend:** Czyta `listing.raw_data?.surface_m2` (number) i wyświetla w karcie/skrócie (np. „54 m², 450 000 zł”).

---

### Kolejność wdrożenia

1. Faza 1 (selektory + fallback regex na tej samej stronie).  
2. Dodać „cena do ustalenia” do `NO_PRICE_PHRASES`.  
3. Faza 2 (follow link) — najpierw ta sama domena, potem znane portale (Facebook → arcabinvestments.com itd.).  
4. Faza 3 (dostosowanie do struktury Facebook / AMW / Komornik).  
5. Faza 4 (metraż) — gdy cena już lepiej zbierana.

---

## 2. Co frontend ma wiedzieć

### Brak zmian w API ani w kontrakcie

- Backend nadal zapisuje do tej samej tabeli **`listings`** w Supabase.
- **`price_pln`** — jak dotąd: **integer, grosze** (np. 45000000 = 450 000 zł). Gdy brak ceny: **`null`**.
- Frontend **nie** dostaje nowych endpointów; tylko odczyt z Supabase.

### Wyświetlanie ceny (bez zmian)

- **Jeśli `listing.price_pln != null`:**  
  `(listing.price_pln / 100).toFixed(0)` (lub format z spacjami) + „ zł”.
- **Jeśli `listing.price_pln === null`:**  
  Pokazać np. **„Cena do ustalenia”** (lub „—”, „Zapytaj o cenę”) — tak jak dziś.
- Po wdrożeniu planu **więcej ofert** będzie miało ustawione `price_pln`; frontend nie musi nic zmieniać w logice, tylko dalej czyta `price_pln` i obsługuje `null`.

### Opcjonalnie: metraż (gdy backend go doda)

- **Jeśli** backend doda kolumnę **`surface_m2`** (numeric):
  - Dodać ją do zapytania `.select(...)` i do typu `Listing`.
  - W karcie oferty / skrócie: np. „54 m²” obok ceny („54 m², 450 000 zł”).
- **Jeśli** na razie metraż jest tylko w **`raw_data.surface_m2`**:
  - Można czytać `listing.raw_data?.surface_m2` i wyświetlać; albo zignorować do czasu kolumny.

### Filtr / sortowanie po cenie

- Filtr „tylko z ceną”: `price_pln IS NOT NULL` (lub po stronie klienta `listing.price_pln != null`).
- Sortowanie po cenie: `order('price_pln', { ascending: true })` — oferty z `null` zwykle lądują na końcu; ewentualnie filtrować je w UI.

### Podsumowanie dla frontendu

| Co | Działanie |
|----|------------|
| **price_pln** | Bez zmian: grosze, `null` = brak ceny → pokazać „Cena do ustalenia”. |
| **Więcej ofert z ceną** | Po wdrożeniu planu backend będzie częściej wypełniał `price_pln`; frontend bez zmian. |
| **surface_m2** (opcjonalnie) | Gdy pojawi się w schema/select — dodać do typu i UI (np. „X m²” w karcie). |
| **raw_data** | Backend może zapisywać np. `price_from_followed_link`, `followed_price_url` — tylko do logów/debugu; frontend nie musi tego wyświetlać. |
| **title** | Backend ustawia krótki tytuł w jednym zdaniu (np. „Mieszkanie 2-pokojowe, 45 m²”) przez `title_extractor`; frontend dalej czyta `listing.title` — bez zmian. |

Frontend **nie musi** wprowadzać żadnych zmian, żeby skorzystać z lepszego zbierania cen; ewentualne zmiany to: obsługa `surface_m2` (gdy będzie) i upewnienie się, że „Cena do ustalenia” jest pokazywana tylko gdy `price_pln === null`.
