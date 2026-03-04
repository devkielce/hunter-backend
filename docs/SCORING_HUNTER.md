# Scoring inwestycyjny (Hunter) – plan i rollout

Dokument odniesienia dla feature'u **investment score**: cel, wzór MVP, zakres „na później”, plan wdrożenia. Wszystkie zmiany w scoringu powinny być spójne z tym dokumentem aż do zakończenia implementacji.

---

## 1. Cel

- Jedna metryka **investment_score (0–100)** dla każdej oferty ze wszystkich scraperów (Komornik, e-licytacje, AMW, Facebook).
- Umożliwienie sortowania i filtrowania ofert według „potencjału inwestycyjnego”.
- MVP opiera się wyłącznie na danych już w systemie + prostych heurystykach (bez AI, bez zewnętrznych API na start).

---

## 2. MVP – z czego się składa

### 2.1 Dane wejściowe

- **price_pln** (już jest)
- **surface_m2** – z `raw_data.surface_m2` lub ekstrakcja z `description` w momencie liczenia score (regex jak w title_extractor)
- **region**, **city**, **source** (już są)
- **Czynsz** – opcjonalnie wyciągany z `description` regexem (jak ceny)

### 2.2 Składniki score'u w MVP

| Składnik | Opis | Źródło w MVP |
|----------|------|-------------------------------|
| **Price Anomaly** | Spread ceny do mediany (im taniej vs „rynek”, tym lepiej) | Mediana `price_per_m2` z ofert w runie (per region) lub domyślna z configu |
| **Yield (buy & hold)** | Yield brutto = czynsz_roczny / cena_zakupu | Czynsz z opisu (regex); gdy brak → 0 |
| **Location** | Atrakcyjność lokacji | Stały słownik region → score w configu |
| **Risk** | Ryzyko źródła + ewentualnie słowa w opisie | Stała mapa source → waga; opcjonalnie regex „spór”, „zajęcie” |

### 2.3 Wzór MVP

```
score_raw = (price_anomaly_norm × 0.35) + (yield_norm × 0.25) + (location_norm × 0.25) − (risk_norm × 0.15)
investment_score = max(0, min(100, score_raw × 100))
```

Wagi konfigurowalne (config). Gdy brak metrażu: price_anomaly = 0. Gdy brak czynszu: yield_norm = 0.

### 2.4 Gdzie liczyć

- W backendzie przy zapisie listingu (przed `upsert_listings`): wywołanie `compute_investment_score(listing, median_by_region, config)`.
- Mediany: z bieżącego batcha ofert w runie (per region); brak mediany → config `scoring.default_median_price_m2`.

### 2.5 Zapis

- MVP: **raw_data.investment_score** (bez migracji).
- Docelowo (Faza 4 rolloutu): kolumna **listings.investment_score** (NUMERIC 0–100, nullable) – sortowanie/filtr w Supabase.

---

## 3. Na później (po MVP)

- Prawdziwe mediany m² z rynku (API, GUS, portale).
- ROI flip (ARV, koszt remontu, PCC, notariusz) – v2 z configiem.
- Agencja vs bezpośrednio – ekstrakcja z opisu (regex lub AI).
- Stan budynku – najpewniej AI lub zaawansowane regex.
- Mikro-lokalizacja (dzielnica, kod) – geokodowanie / AI.
- Cash ROI z kredytem – v2 z parametrami.

---

## 4. Plan rolloutu

| Faza | Opis | Status |
|------|------|--------|
| **0** | Dokument SCORING_HUNTER i akceptacja planu | ✅ Zrobione |
| **1** | Metraż: ekstrakcja i zapis surface_m2 (raw_data lub kolumna) – zależne od planu cen | Częściowo (ekstrakcja w scoringu z opisu) |
| **2** | Moduł investment_score.py: wzór MVP, config (wagi, risk per source, location per region) | ✅ Zrobione |
| **3** | Mediany z runu + wywołanie scoringu w run.py i process_apify_dataset | ✅ Zrobione |
| **4** | Migracja DB: kolumna investment_score; zapis przy upsercie; frontend sort/filter | Do zrobienia |
| **5** | Rozszerzenia: mediany z API, ROI flip, agencja, stan – zgodnie z sekcją „Na później” | Backlog |

---

## 5. Odniesienia w kodzie

- **Moduł scoringu:** `hunter/investment_score.py`
- **Wywołanie:** po zbudowaniu listinguów, przed `for_supabase` / `upsert_listings` (`run.py`, `apify_facebook.process_apify_dataset`).
- **Config:** `scoring.weights`, `scoring.risk_by_source`, `scoring.location_score_by_region`, `scoring.default_median_price_m2`.
- **Frontend:** odczyt `listing.raw_data?.investment_score` (liczba 0–100); sortowanie/filtr po tej wartości. Później kolumna `investment_score`.
