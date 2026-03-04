# Ekstrakcja krótkiego tytułu (jedno zdanie, bez AI)

**Zaimplementowano.** Moduł `hunter.title_extractor` wyciąga z opisu/tytułu zwięzły tytuł w jednym zdaniu (np. „Mieszkanie 2-pokojowe, 45 m²”, „Dom, 3 kondygnacje”, „Kawalerka, 28 m²”). Używane w: Facebook (Apify), AMW, Komornik, e-licytacje.

---

## Cel

Tytuł oferty ma opisywać rzeczywistość w max jednym zdaniu: typ nieruchomości (mieszkanie, dom, działka, kawalerka, lokal użytkowy), ewentualnie liczba pokoi, metraż, kondygnacje. Bez AI — tylko regex i słowa kluczowe.

---

## Logika (`title_extractor.py`)

1. **Typ:** dopasowanie słów (kolejność ma znaczenie): kawalerka, lokal użytkowy, dom (jednorodzinny / wolnostojący), dom, działka, mieszkanie, segment, blok.
2. **Pokoje:** regex na „X pokoje/pokoi/pokojowe”, „kawalerka” → 1; tylko dla typu Mieszkanie/Segment: dopisanie „2-pokojowe” itd.
3. **Metraż:** regex na „X m²”, „X m2”, „pow. X”, „powierzchnia X”; sensowne przedziały (np. 5–5000 m²).
4. **Kondygnacje/piętro:** „X kondygnacje”, „parter”, „X piętro” — głównie dla Dom.
5. **Składanie:** `"{typ}, {pokojowe}, {metraż}, {kondygnacje}"` w jednym zdaniu, max 120 znaków.
6. **Fallback:** gdy nic nie znaleziono — przekazany `fallback` (oryginalny tytuł) lub pierwsza linia/pierwsze zdanie z tekstu.

---

## Gdzie używane

| Źródło    | Wejście                    | Fallback                    |
|----------|----------------------------|-----------------------------|
| Facebook | tekst posta (title+message+…) | pierwsze 500 znaków / cały tekst |
| AMW      | description + title karty  | „Nieruchomość AMW — …”      |
| Komornik | title + description detalu | „Licytacja komornicza”      |
| E-licytacje | title + description detalu | „Licytacja sądowa”        |

Frontend nie wymaga zmian — pole `listing.title` nadal string; treść jest po prostu krótsza i bardziej opisowa.
