# Filtr „tylko nieruchomości” dla Facebook (Apify)

**Stosowany wyłącznie do źródła Facebook.** E-licytacje i AMW nie używają tego filtra – tam treść to z założenia oferty nieruchomości, więc nie ma kolizji.

---

## Cel

W grupach na Facebooku ludzie wrzucają wszystko: skutery, biżuterię, nieruchomości itd. Ten filtr zostawia w pipeline tylko posty dotyczące **nieruchomości** (mieszkanie, dom, działka, wynajem itd.) i dopiero dla nich wyciąga cenę (z tekstu lub z linku).

---

## Kroki (zaimplementowane)

1. **Listy słów (w `apify_facebook.py`):**
   - **REAL_ESTATE_KEYWORDS** – post musi zawierać co najmniej jedno (np. nieruchomość, mieszkanie, dom, działka, lokal, wynajem, pokoje, metraż, m², czynsz, ul. …).
   - **NON_REAL_ESTATE_KEYWORDS** – jeśli w poście jest któreś z tych słów (np. skuter, motor, biżuteria, rower, samochód, meble, telefon, zwierzę…), post jest odrzucany.

2. **Funkcja `passes_real_estate_filter(text)`:**  
   `True` tylko gdy w tekście jest co najmniej jedno słowo z listy nieruchomości **i** brak słów z listy wykluczających.

3. **Pipeline Facebook:**  
   W `normalize_facebook_item()` najpierw sprawdzany jest `passes_real_estate_filter(text)`. Jeśli `False` → post jest pomijany (nie trafia do `listings`). Dla postów, które przejdą, dalej: normalizacja, wyciąganie ceny z tekstu, ewentualnie follow-link po cenę.

4. **Cena:**  
   Dla postów uznanych za nieruchomości działa dotychczasowa logika: `price_pln_from_full_text(text)`, a gdy brak – wejście w pierwszy link do oferty i cena ze strony docelowej.

---

## Rozszerzanie list

- **Więcej nieruchomości:** dopisać wyrazy do `REAL_ESTATE_KEYWORDS` (np. garaż, pokój, wynajem pokoju).
- **Więcej wykluczeń:** dopisać do `NON_REAL_ESTATE_KEYWORDS` (np. kolejne kategorie ogłoszeń spoza nieruchomości).

Opcjonalnie można dodać scoring (np. +1 za słowo RE, −1 za non-RE) i próg zamiast twardego „wszystko albo nic”; na start wystarczy logika „co najmniej jedno RE i zero non-RE”.

---

## E-licytacje i AMW

- **E-licytacje:** scraper chodzi po stronach aukcji; treść to oferty/aukcje. Filtr słów „czy to nieruchomość” **nie jest** stosowany.
- **AMW:** serwis tylko nieruchomości; listy ofert są już po stronie nieruchomości. Filtr **nie jest** stosowany.

Żadna zmiana w tym dokumencie ani w filtrze Facebook nie wpływa na działanie e-licytacji ani AMW.
