# Grafikomat: plan techniczny prototypu

Plan do akceptacji przed pisaniem kodu aplikacji. Zakres i wymagania: [spec.md](spec.md).
Kod, nazwy w kodzie i commity po angielsku; teksty interfejsu po polsku.

## 1. Architektura

```
przeglądarka (telefon / komputer)
        │  https, jedna domena
        ▼
     Caddy ──── /            → statyczny build frontendu (React + Vite)
        │
        └────── /api/*       → Django + Django Ninja (gunicorn)
                                   │
                                   ▼
                              PostgreSQL  ◄──── worker Procrastinate (ten sam kod Django)
                     (dane + kolejka zadań)        └─ generator (OR-Tools CP-SAT), walidator,
                                                      interpretacja próśb (Claude API)
```

Kontenery Docker Compose: `caddy`, `api`, `worker`, `db`. Lokalnie do tego tryb deweloperski: Vite dev server z proxy `/api` do Django.

### Układ repozytorium

```
backend/
  config/                 ustawienia Django, urls, api (NinjaAPI)
  apps/
    accounts/             User (numer telefonu), logowanie kodem SMS, sesje, limity
    tenancy/              Company, LocationGroup, Location, Membership, Invitation, izolacja firm
    billing/              Subscription, AccessCode, CodeRedemption, GenerationUsage
    staffing/             Position, ShiftType, StaffingRule, StaffingException, EmployeeProfile
    availability/         AvailabilityDay, AvailabilityPattern, TextRequest
    rules/                RuleSetting (kolejność, twarda/miękka), WeightProfile
    scheduling/           SchedulePeriod, ScheduleVersion, Shift, Assignment, AssignmentEvent, GenerationRun
    marketplace/          ShiftOffer, ShiftClaim (oddawanie zmian)
    notifications/        Notification (tylko w aplikacji)
    reports/              godziny w miesiącu, CSV
  engine/                 czysty Python, bez Django: dane wejściowe jako dataclasses
    problem.py            Problem, Employee, Slot, Rule, Request… (wspólny opis zadania)
    validator.py          niezależny walidator twardych reguł + liczenie naruszeń miękkich
    scoring.py            trzy wartości oceny (dziury, zasady menedżera %, prośby %)
    solver.py             model CP-SAT
    explain.py            szybkie wyjaśnienia (bez ponownego uruchamiania solvera)
    rules_catalog.py      gotowa lista zasad: kod, parametry, sposób liczenia naruszenia
  tests/
frontend/
  src/routes/             TanStack Router (pliki tras)
  src/api/                klient wygenerowany przez orval z /api/openapi.json
  src/components/ui/      komponenty shadcn/ui ostylowane tokenami
  src/styles/tokens.css   tokeny wizualne (etap 6)
deploy/Caddyfile
docker-compose.yml
.env.example
CLAUDE.md
docs/spec.md, docs/plan.md
```

Kluczowa decyzja: `engine/` nie zna Django. Warstwa `scheduling` buduje z bazy obiekt `Problem`, a solver, walidator, ocena i wyjaśnienia pracują tylko na nim. Dzięki temu walidator i solver testujemy szybko, bez bazy, a walidator jest naprawdę niezależny od solvera (osobny kod, ten sam opis zadania).

### Izolacja firm

- Każda tabela z danymi firmy ma kolumnę `company_id` (NOT NULL, FK, indeks), także tabele podrzędne (np. `Assignment`), żeby filtr nie zależał od złączeń.
- Wszystkie endpointy firmowe przechodzą przez jedną zależność `tenant_context(request)`, która z sesji i członkostw ustala firmę i role, i zwraca querysety już ograniczone (`Model.objects.for_company(company)`). Zwykły `Model.objects` w kodzie API jest blokowany testem (grep w CI) poza wyznaczonymi miejscami.
- Klucze obce między tabelami tej samej firmy sprawdzane przy każdym zapisie (`CompanyOwnedModel.save()`/`clean()`), a powiązania wiele-do-wielu sygnałem `m2m_changed` (np. stanowisko z innej firmy nie może trafić do pracownika). `company` uzupełnia się z rodzica (np. z lokalu).
- Test izolacji: dwie firmy w danych przykładowych; dla każdego endpointu z listy próba odczytu i zapisu obiektu drugiej firmy musi dać 404. Od etapu 2 testy sprawdzają też, że każda tabela firmowa ma `company_id` i że `api.py` nie używa `Model.objects` bez `for_company()` (wyjątek oznaczony komentarzem `# tenant-ok: powód`).
- Row Level Security w Postgresie świadomie odkładamy (więcej pracy z migracjami i workerem); można dodać przed wdrożeniem.

### Kolejka i generator

- `POST /generate` w jednej transakcji: zapis `GenerationRun(status=queued)` i `procrastinate defer` zadania `solve_schedule(run_id)`.
- Kolejka `solver` z osobnym workerem o współbieżności 1 (zmienna `SOLVER_CONCURRENCY`, max 2). Kolejka `default` dla interpretacji próśb i drobnych zadań.
- Limit czasu solvera `SOLVER_TIME_LIMIT_S=30`; zwracamy najlepsze znalezione rozwiązanie, status `optimal` / `feasible` / `timeout_no_solution`.
- Frontend odpytuje `GET /generation-runs/{id}` co 1–2 s (bez websocketów w prototypie).

## 2. Modele danych

Wszystkie tabele firmowe mają `company_id`; pominięte poniżej dla czytelności. `id` to UUID, czasy `timestamptz`, daty `date`.

### Konta i firmy

| Model | Pola | Ograniczenia |
|---|---|---|
| `User` | phone_e164, first_name, last_name, is_staff | phone unikalny; jedno konto na numer w całym systemie (bez company_id) |
| `LoginCode` | phone, code_hash, expires_at, attempts, used_at, ip | 6 cyfr, 5 min, max 5 prób; przechowujemy tylko hash |
| `Company` | name, created_by | |
| `LocationGroup` | name | opcjonalna |
| `Location` | name, address, group (nullable), timezone (Europe/Warsaw), schedule_period (week/month), availability_deadline_days | |
| `Membership` | user, company, role (owner/manager/employee), locations (M2M dla menedżera) | unikalne (user, company) |
| `Invitation` | location, phone, role, status (pending/accepted/declined/cancelled), invited_by, decided_at | częściowy indeks unikalny (location, phone) WHERE status='pending' |

### Subskrypcja

| Model | Pola | Ograniczenia |
|---|---|---|
| `AccessCode` | code_hash + prefiks do podglądu, days (30/60), max_uses (1), uses, valid_until, note | bez company_id (globalny, tworzy superadmin) |
| `CodeRedemption` | code, company, user, redeemed_at, days_added | |
| `CodeAttempt` | user, ip, at, success | do limitu prób |
| `Subscription` | company, ends_at, source (code/stripe), status liczony z ends_at | jedna na firmę; kod przedłuża od max(ends_at, teraz) |
| `GenerationUsage` | company, month, count | limit 30 na miesiąc (`GENERATION_MONTHLY_LIMIT`) |

### Ustawienia lokalu i pracownicy

| Model | Pola | Uwagi |
|---|---|---|
| `Position` | location, name | np. Sprzedawca, Piekarz, Kierownik zmiany |
| `ShiftType` | location, name, start_time, end_time, kind (fixed/flexible), is_closing | koniec przed początkiem = przez północ |
| `StaffingRule` | location, weekday, shift_type, position, count, start/end (tylko dla zmian z dowolnymi godzinami) | unikalne (location, weekday, shift_type, position) |
| `StaffingException` | location, date, shift_type, position, count, start/end (opcjonalnie inne godziny) | np. Wigilia, dzień bez obsady (count=0) |
| `EmployeeProfile` | membership, home_location, positions (M2M), contract (civil/employment), max_hours_month, target_hours_month, is_active | zlecenie domyślne |

### Dyspozycyjność i prośby

| Model | Pola | Uwagi |
|---|---|---|
| `AvailabilityDay` | employee, date, state (cannot/prefer_not/neutral/prefer), from_time, to_time (opcjonalne), source (manual/pattern/copy) | unikalne (employee, date); brak wiersza = brak zgłoszenia |
| `AvailabilityPattern` | employee, weekday, state, from/to, repeat_until | "powtarzaj co tydzień do [data]"; rozwijany do `AvailabilityDay` przy zapisie |
| `AvailabilitySubmission` | employee, period, submitted_at | do listy "kto nie zgłosił" |
| `TextRequest` | employee, period, text, status (new/interpreted/needs_manager/rejected), interpretation (JSON), employee_corrected, manager_priority (lower/normal/higher), manager_rejected | interpretacja: type, subject_employee, dates, level, confidence, summary |

### Zasady

| Model | Pola | Uwagi |
|---|---|---|
| `RuleSetting` | scope (group lub location; dokładnie jedno z dwóch), rule_code, enabled, is_hard, position (kolejność), params (JSON) | ustawienie lokalu nadpisuje grupę dla tego samego rule_code |
| `WeightProfile` | scope (group lub location), manager_share (0.8), level_weights, rank_decay, stability_penalty | niewidoczny w interfejsie, edytowalny w adminie |

Katalog zasad w kodzie (`engine/rules_catalog.py`), np.: min. 11 h między zmianami, max 6 dni z rzędu, równy podział weekendów, równy podział zamknięć, cel godzin, osobiste maksimum, preferowany typ zmiany na stanowisku, min. jedna osoba z danym stanowiskiem na zamknięciu itp. Lokal nie tworzy zasad z niczego, tylko włącza i ustawia parametry z katalogu.

### Grafik

| Model | Pola | Uwagi |
|---|---|---|
| `SchedulePeriod` | location, start, end, status (collecting/draft/published) | |
| `ScheduleVersion` | period, number, status (draft/published/superseded), created_by, from_run, scores (JSON), is_complete | publikacja = nowa wersja, stare zostają |
| `Shift` | version, location, date, shift_type, position, start_at, end_at, slot_key | slot obsady na jedną osobę; godziny skopiowane, żeby zmiana ustawień nie psuła starych grafików; `slot_key` (data, zmiana, stanowisko, numer miejsca) jest stały między wersjami |
| `Assignment` | shift (jeden do jednego), employee (nullable = dziura), pinned, borrowed (z innego lokalu) | dziura nie może być przypięta |
| `AssignmentEvent` | location, period, slot_key, from_employee, to_employee, reason (generated/manual/offer/swap), at, by | historia; podstawa pod późniejsze zamiany |
| `GenerationRun` | scope (location/group), period(s), status, started/finished, solver_status, time_ms, error | wynik: wersje z `ScheduleVersion.from_run` (generowanie dla grupy daje po jednej wersji na lokal) |

### Oddawanie zmian i powiadomienia

| Model | Pola |
|---|---|
| `ShiftOffer` | assignment, offered_by, status (open/claimed/approved/rejected/cancelled/expired) |
| `ShiftClaim` | offer, employee, status, decided_by |
| `Notification` | user, kind, payload (JSON), read_at |

## 3. Generator

Zmienne: `x[e, s] ∈ {0,1}` dla pracownika `e` i slotu `s` (zmiana × stanowisko × kolejne miejsce), tylko dla par dopuszczalnych (właściwe stanowisko, lokal domowy, brak "nie mogę"). `u[s]` = slot nieobsadzony.

Twarde: każdy slot ma jedną osobę albo `u[s]=1`; brak nakładających się zmian; przypięte przypisania; dni minione zamrożone; zasady "bez wyjątków"; dla umowy o pracę dodatkowo 11 h odpoczynku, max 8 h na dobę, 35 h odpoczynku tygodniowego.

Cel w dwóch fazach (leksykograficznie): faza 1 minimalizuje `Σ u[s]`, faza 2 przy tej liczbie dziur minimalizuje karę:

```
kara = manager_share × Σ_z  w_z × naruszenie_z            (zasady menedżera)
     + (1 − manager_share) × Σ_p  w_p × naruszenie_p      (prośby pracowników)
     + stability_penalty × liczba zmian względem opublikowanej wersji
```

- `w_z` z miejsca na liście: najwyższa zasada dostaje największą wagę, każda kolejna mniejszą (stały współczynnik `rank_decay`, np. 0,75). Dzięki temu "wszystko najważniejsze" jest niemożliwe z definicji.
- `w_p` z poziomu prośby (bardzo ważne / ważne / mile widziane) i korekty menedżera (ważniejsza / mniej ważna).
- Czas dzielony między fazy (np. 40/60 % limitu). Wynik fazy 1 trafia jako podpowiedź do fazy 2.
- Generowanie dla grupy = jeden model dla wszystkich lokali grupy (wspólne godziny pracownika), ale przypisania tylko do lokalu domowego; pożyczenie do innego lokalu robi menedżer ręcznie.
- Kod przygotowany pod 3 warianty: funkcja `solve(problem, profile, diversity_from=[...])`; drugi i trzeci wariant to inne `manager_share` i ograniczenie min. 15 % różnych przypisań. W tej wersji wołamy ją raz.

Ocena (`scoring.py`, ten sam kod dla każdego wariantu i dla ręcznej edycji): liczba dziur, "zasady menedżera" % i "prośby pracowników" % wg wzoru `100 × (1 − Σ w_i v_i / Σ w_i)`. Grafik z dziurami ma flagę "niekompletny" i nie pokazuje zielonej oceny.

Walidator ma ostatnie słowo: wynik solvera, który nie przejdzie walidatora, nie zostaje zapisany jako wersja (błąd w logach, komunikat dla menedżera).

## 4. Endpointy (Django Ninja, prefiks `/api`)

Logowanie i konto
- `POST /auth/request-code` (phone) · `POST /auth/verify-code` (phone, code) · `POST /auth/logout` · `GET /me`
- `GET /me/invitations` · `POST /invitations/{id}/accept` · `POST /invitations/{id}/decline`
- `POST /companies` (rejestracja menedżera: nazwa firmy, opcjonalnie kod) · `GET /companies/{id}/subscription` · `POST /companies/{id}/subscription/redeem`

Ustawienia (menedżer)
- `GET/POST /groups`, `GET/POST/PATCH /locations`
- `GET/POST/PATCH/DELETE /locations/{id}/positions`, `/shift-types`, `/staffing-rules`, `/staffing-exceptions`
- `GET/PATCH /locations/{id}/employees`, `POST /locations/{id}/invitations`, `POST /invitations/{id}/cancel`

Dyspozycyjność i prośby
- `GET /me/availability?period=` · `PUT /me/availability` (lista dni) · `POST /me/availability/pattern` · `POST /me/availability/copy-previous`
- `POST /me/requests` · `PATCH /me/requests/{id}` (poprawka interpretacji) · `GET /me/requests`
- `GET /locations/{id}/availability-grid?period=` · `GET /locations/{id}/requests?period=` · `PATCH /requests/{id}` (odrzuć / ważniejsza / mniej ważna) · `GET /locations/{id}/missing-availability?period=`

Zasady
- `GET /scopes/{type}/{id}/rules` · `PUT /scopes/{type}/{id}/rules` (cała lista z kolejnością) · `POST /scopes/{type}/{id}/rules/preview` (skutek zmiany na ostatnim okresie)

Grafik
- `GET/POST /locations/{id}/periods` · `POST /periods/generate` (lokal lub grupa) → `GenerationRun`
- `GET /generation-runs/{id}` · `GET /versions/{id}` (zmiany, przypisania, ocena, wyjaśnienia)
- `POST /versions/{id}/validate` (proponowana zmiana; odpowiedź: naruszenia + nowa ocena) · `PATCH /versions/{id}/assignments` (przeniesienie, przypięcie)
- `POST /versions/{id}/publish` · `GET /assignments/{id}/explain?deep=false`
- `GET /me/schedule` (tylko opublikowany grafik na najbliższy okres, suma godzin, współpracownicy na zmianie)

Oddawanie zmian i powiadomienia
- `POST /me/assignments/{id}/offer` · `GET /me/offers/available` · `POST /offers/{id}/claim` · `POST /claims/{id}/approve|reject`
- `GET /me/notifications` · `POST /me/notifications/read`

Raporty
- `GET /reports/hours?month=&scope=` · `GET /reports/hours.csv`

Admin Django: kody subskrypcji (generowanie partii, podgląd użyć), firmy, profile wag.

## 5. Ekrany

Pracownik (telefon)
1. Logowanie: numer telefonu → kod (duże pola, automatyczne przejście, "wyślij ponownie" z odliczaniem).
2. Zaproszenie: nazwa firmy i lokalu, Akceptuj / Odrzuć.
3. Mój grafik: lista najbliższych zmian (data, lokal, godziny, stanowisko, kto ze mną), suma godzin, "Oddaj zmianę", sekcja "Zmiany do wzięcia" z przyciskiem "Biorę".
4. Kiedy mogę: kalendarz okresu z czterema stanami (kolor + ikona + podpis), stuknięcie przełącza, przeciągnięcie zaznacza kilka dni, "Powtarzaj co tydzień do…", "Skopiuj z poprzedniego miesiąca", termin zgłoszenia; na dole "Coś jeszcze?" na prośbę tekstem i pokazanie, jak system ją zrozumiał.

Menedżer (komputer)
1. Rejestracja firmy i kod dostępu (także później w Ustawieniach → Subskrypcja).
2. Widok zbiorczy grupy (ekran startowy): lokale w wierszach, stan okresu każdego lokalu (zbieranie dyspozycji / szkic / opublikowany), kto nie zgłosił dyspozycji, przycisk "Ułóż grafik dla wszystkich".
3. Ustawienia lokalu: stanowiska, zmiany i godziny, obsada (tabela dzień tygodnia × zmiana × stanowisko) z wyjątkami, okres i termin dyspozycji.
4. Pracownicy: lista, zaproszenia po numerze, stanowiska, umowa, maksimum i cel godzin.
5. Dyspozycje: siatka pracownicy × dni, lista próśb z interpretacją i akcjami, lista osób bez zgłoszenia.
6. Zasady: jedna lista do przeciągania, przełącznik włącz/wyłącz, "bez wyjątków", parametry, podgląd skutku przed zapisaniem.
7. Grafik: siatka dni × zmiany, trzy wartości oceny, dziury wyraźnie oznaczone, przeciąganie i przypinanie z walidacją na żywo, wyjaśnienia po kliknięciu, publikacja i historia wersji.
8. Oddane zmiany: lista do zatwierdzenia.
9. Godziny: podsumowanie miesiąca z podziałem na lokale, eksport CSV.

Każdy ekran ma stan pusty, ładowania i błędu.

## 6. Etapy (jeden etap = jeden wątek = jeden pull request)

| # | Zakres | Testy |
|---|---|---|
| 1 | Szkielet repo: backend Django + Ninja (healthcheck, OpenAPI), worker Procrastinate z zadaniem testowym, frontend Vite + React + TanStack + Tailwind + orval z jedną stroną, Docker Compose (api, worker, db, caddy), CLAUDE.md, docs, linter (ruff, eslint), CI na GitHub Actions | healthcheck, zadanie w kolejce wykonane przez worker, build frontendu |
| 2 | Modele danych, izolacja firm, admin, dane przykładowe (komenda `seed_demo`) | izolacja firm, ograniczenia unikalności |
| 3 | Logowanie kodem SMS, sesje, limity, zaproszenia, kody subskrypcji, tryb tylko do odczytu | logowanie i limity, zaproszenia, kody i przedłużanie |
| 4 | `engine/`: Problem, walidator, ocena | oba typy umów, przypadki graniczne (północ, zmiana czasu, styk zmian, 11 h co do minuty) |
| 5 | Generator w workerze, limit czasu, stabilność, limit generowań | brak naruszeń twardych reguł, limit czasu, stabilność, dziury przy braku ludzi |
| 6 | Kierunek wizualny i tokeny (czekam na akceptację), potem ekrany pracownika | zrzuty telefon/komputer |
| 7 | Ekrany menedżera: ustawienia lokalu, pracownicy, dyspozycje, zasady z podglądem skutku | |
| 8 | Generowanie z interfejsu, ocena, wyjaśnienia, ręczna edycja, publikacja, raport godzin i CSV | walidacja ręcznej edycji |
| 9 | Oddawanie zmian, historia przypisań, powiadomienia w aplikacji | kto dostaje powiadomienie, zatwierdzenie |
| 10 | Interpretacja próśb przez Claude (structured outputs), tryb bez klucza, README końcowe | z atrapą klienta API; bez klucza → do menedżera |

Etap 1 robię w tym wątku po akceptacji planu; kolejne poproszę jako osobne wątki.

## 7. Założenia (do potwierdzenia albo poprawy)

1. Dyspozycyjność: stan na cały dzień, z opcjonalnym zakresem godzin ("chętnie od 14:00"), wybieranym z listy, nie pisanym. Domyślnie cały dzień.
2. Brak zgłoszenia dyspozycji = "obojętnie", ale osoba jest na liście "nie zgłosił" u menedżera.
3. Generator przypisuje ludzi tylko do ich lokalu domowego; praca w innym lokalu tylko ręcznie albo przez wzięcie oddanej zmiany.
4. Zmiany typu "dowolne godziny" generator traktuje jak sloty z godzinami ustawionymi w obsadzie lub wyjątku na dany dzień; menedżer może też dodać zmianę z dowolnymi godzinami ręcznie.
5. Tydzień zaczyna się w poniedziałek, strefa czasowa Europe/Warsaw, godziny zmian liczone w czasie lokalnym z uwzględnieniem zmiany czasu.
6. Menedżer też może mieć profil pracownika (np. kierownik na umowie o pracę w grafiku).
7. Rejestracja firmy możliwa bez kodu; bez aktywnej subskrypcji firma jest w trybie tylko do odczytu, dopóki nie wpisze kodu.
8. Odświeżanie wyniku generowania przez odpytywanie co 1–2 s, bez websocketów.
9. CI na GitHub Actions (ruff, pytest, eslint, typecheck, build) to część stosu narzędzi, nie aplikacji; dodam w etapie 1, jeśli się zgadzasz.
10. Row Level Security w Postgresie odłożone; izolacja w warstwie aplikacji z testami.
