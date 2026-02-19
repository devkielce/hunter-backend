# Kryteria wyszukiwania — licytacje.komornik.pl

Scraper komorniczy używa **jednego źródła**: [https://licytacje.komornik.pl](https://licytacje.komornik.pl). Poniżej kryteria, na podstawie których budowana jest wyszukiwarka i które można zmienić w konfiguracji.

---

## 1. Strona listy ofert (URL)

- **Baza:** `https://licytacje.komornik.pl`
- **Lista:** ` /Notice/Filter/{categoryId}`

Obecnie używana jest **jedna kategoria nieruchomości**:

| ID  | Kategoria (na stronie) |
|-----|------------------------|
| 30  | **mieszkania**         |

Inne możliwe ID (nieużywane domyślnie): 29=domy, 31=garaże i miejsca postojowe, 32=grunty, 33=lokale użytkowe, 34=magazyny i hale, 35=inne, 36=statki morskie.

**Pełny URL listy:**  
`https://licytacje.komornik.pl/Notice/Filter/30`  
Paginacja: `?page=2`, `?page=3`, …

---

## 2. Województwo (region)

- **Domyślnie:** wszystkie regiony (każda oferta ma pole `region` do filtrowania we frontendzie).
- **Opcjonalny filtr:** w `config.yaml` ustaw `scraping.komornik_region` np. na `"świętokrzyskie"`, żeby ograniczyć do jednego województwa. Po pobraniu strony listy sprawdzana jest kolumna **„Miasto (Województwo)”**; do wyników trafiają tylko wiersze, w których ta kolumna zawiera podany tekst (bez rozróżniania wielkości liter).
- **Konfiguracja:** `komornik_region: ""` = wszystkie regiony; `komornik_region: "świętokrzyskie"` = tylko świętokrzyskie.

---

## 3. Paginacja

- **Kryterium:** przeglądane są kolejne strony listy, dopóki na stronie są oferty.
- **Limit stron:** `config.yaml` → `scraping.max_pages_auctions` (domyślnie 50). Przy jednym województwie zwykle wystarczy mniej stron.

---

## 4. Podsumowanie (domyślna konfiguracja)

| Kryterium      | Wartość / zachowanie |
|----------------|----------------------|
| Źródło         | https://licytacje.komornik.pl |
| Typ mienia     | Nieruchomości        |
| Kategoria      | Mieszkania (Filter/30) |
| Województwo    | Wszystkie (domyślnie); opcjonalnie jeden np. świętokrzyskie |
| Filtr regionu  | Po kolumnie „Miasto (Województwo)”; gdy `komornik_region: ""` — brak filtra, każde ogłoszenie ma pole `region` |
| Paginacja      | Tak, do `max_pages_auctions` stron |

Żadne inne kryteria (np. cena, data) nie są na razie ustawiane w zapytaniu — strona listy zwraca domyślną kolejność; filtrowanie po województwie odbywa się po stronie scrapera na podstawie tabeli.
