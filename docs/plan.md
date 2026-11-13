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
- Limit czasu solvera `SOLVER_TIME_LIMIT_S=30`; zwracamy najlepsze znalezione rozwiązanie, status `optimal` / `feasible` / `timeout_no_solution` / `infeasible` (sprzeczne zasady "bez wyjątków" albo przypięcia; z wyjaśnieniem dla menedżera).
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
| `Invitation` | location, phone, first_name, last_name (opcjonalne), role, status (pending/accepted/declined/cancelled), invited_by, decided_at | częściowy indeks unikalny (location, phone) WHERE status='pending' |

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
- Każdy lokal generujemy osobno (decyzja Piotra z 12.11.2026: lokale są niezależne, każdy z własnymi zasadami i wagami); "Ułóż grafik dla wszystkich" uruchamia osobne generowanie dla każdego lokalu. Przypisania tylko do lokalu domowego; pożyczenie do innego lokalu robi menedżer ręcznie. Opublikowane zmiany tych samych osób w innych lokalach liczą się do odpoczynku i nakładania.
- Kod przygotowany pod 3 warianty: funkcja `solve(problem, profile, diversity_from=[...])`; drugi i trzeci wariant to inne `manager_share` i ograniczenie min. 15 % różnych przypisań. W tej wersji wołamy ją raz.

Ocena (`scoring.py`, ten sam kod dla każdego wariantu i dla ręcznej edycji): liczba dziur, "zasady menedżera" % i "prośby pracowników" % wg wzoru `100 × (1 − Σ w_i v_i / Σ w_i)`. Grafik z dziurami ma flagę "niekompletny" i nie pokazuje zielonej oceny.

Walidator ma ostatnie słowo: wynik solvera, który nie przejdzie walidatora, nie zostaje zapisany jako wersja (błąd w logach, komunikat dla menedżera).

## 4. Endpointy (Django Ninja, prefiks `/api`)

Logowanie i konto
- `POST /auth/request-code` (phone, purpose: login/register) · `POST /auth/verify-code` (phone, code) · `POST /auth/logout` · `GET /me` (ustawia też ciasteczko CSRF) · `PATCH /me` (imię i nazwisko)
- `GET /me/invitations` · `POST /invitations/{id}/accept` · `POST /invitations/{id}/decline`
- `POST /companies` (rejestracja menedżera: nazwa firmy, opcjonalnie kod) · `GET /companies/{id}/subscription` · `POST /companies/{id}/subscription/redeem`

Ustawienia (menedżer)
- `GET/POST /groups`, `GET/POST/PATCH /locations`
- `GET/POST/PATCH/DELETE /locations/{id}/positions`, `/shift-types`, `/staffing-rules`, `/staffing-exceptions`
- `GET/PATCH /locations/{id}/employees`, `GET/POST /locations/{id}/invitations`, `POST /invitations/{id}/cancel`

Dyspozycyjność i prośby
- `GET /me/availability?period=` · `PUT /me/availability` (lista dni) · `POST /me/availability/pattern` · `POST /me/availability/copy-previous`
- `POST /me/requests` · `PATCH /me/requests/{id}` (poprawka interpretacji) · `GET /me/requests`
- `GET /periods/{id}/availability` (siatka, kto wysłał, zmiany po terminie) · `GET /periods/{id}/requests` · `PATCH /requests/{id}` (odrzuć / ważniejsza / mniej ważna)

Zasady
- `GET /scopes/{type}/{id}/rules` · `PUT /scopes/{type}/{id}/rules` (cała lista z kolejnością) · `POST /scopes/{type}/{id}/rules/preview` (skutek zmiany na ostatnim okresie)

Grafik
- `GET/POST /locations/{id}/periods` · `POST /periods/generate` (jeden lub kilka okresów; osobne `GenerationRun` dla każdego lokalu)
- `GET /generation-runs/{id}` · `GET /versions/{id}` (zmiany, przypisania, ocena, zasady, niespełnione prośby, historia wersji)
- `POST /versions/{id}/check` (proponowana zmiana; odpowiedź: naruszenia + nowa ocena) · `PATCH /versions/{id}/assignments` (wpisanie, zamiana, zostawienie bez obsady) · `POST /versions/{id}/shifts/{shift_id}/pin`
- `POST /versions/{id}/draft` (poprawka opublikowanego grafiku) · `POST /versions/{id}/publish` · `GET /versions/{id}/shifts/{shift_id}/explain`
- `GET /me/schedule` (tylko opublikowany grafik na najbliższy okres, suma godzin, współpracownicy na zmianie)

Oddawanie zmian i powiadomienia
- `POST /me/shifts/{assignment_id}/offer` · `POST /offers/{id}/cancel` · `GET /me/offers?company_id=` · `POST /offers/{id}/claim` · `POST /claims/{id}/withdraw`
- `GET /manager/offers?company_id=` · `POST /claims/{id}/approve` · `POST /claims/{id}/reject`
- `GET /me/notifications?company_id=` · `POST /me/notifications/read`

Raporty
- `GET /reports/hours?company_id=&month=` · `GET /reports/hours.csv?company_id=&month=`

Admin Django: kody subskrypcji (generowanie partii, podgląd użyć), firmy, profile wag.

## 5. Ekrany

Pracownik (telefon)
1. Logowanie: numer telefonu → kod (duże pola, automatyczne przejście, "wyślij ponownie" z odliczaniem).
2. Zaproszenie: nazwa firmy i lokalu, Akceptuj / Odrzuć.
3. Mój grafik: lista najbliższych zmian (data, lokal, godziny, stanowisko, kto ze mną), suma godzin, "Oddaj zmianę", sekcja "Zmiany do wzięcia" z przyciskiem "Biorę".
4. Kiedy mogę: kalendarz okresu z czterema stanami (kolor + ikona + wzór, podpis na przyciskach pędzla), wybór stanu "pędzlem" na dole, potem stuknięcie lub przeciągnięcie po dniach, "Powtarzaj co tydzień do…", "Skopiuj z poprzedniego miesiąca", termin zgłoszenia; na dole "Coś jeszcze?" na prośbę tekstem i pokazanie, jak system ją zrozumiał.

Menedżer (komputer)
1. Rejestracja firmy i kod dostępu (także później w Ustawieniach → Subskrypcja).
2. Widok zbiorczy grupy (ekran startowy): lokale w wierszach, stan okresu każdego lokalu (zbieranie dyspozycji / szkic / opublikowany), kto nie zgłosił dyspozycji, przycisk "Ułóż grafik dla wszystkich" (osobne generowanie dla każdego lokalu), przycisk "Poproś o dyspozycje" (powiadomienie do pracowników z okresem i terminem).
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

1. Dyspozycyjność: stan na cały dzień, z opcjonalnym zakresem godzin wybieranym z listy, nie pisanym (znaczenie godzin: spec.md, Pracownik, punkt 2). Domyślnie cały dzień.
2. Brak zgłoszenia dyspozycji = "obojętnie", ale osoba jest na liście "nie zgłosił" u menedżera.
3. Generator przypisuje ludzi tylko do ich lokalu domowego; praca w innym lokalu tylko ręcznie albo przez wzięcie oddanej zmiany.
4. Zmiany typu "dowolne godziny" generator traktuje jak sloty z godzinami ustawionymi w obsadzie lub wyjątku na dany dzień; menedżer może też dodać zmianę z dowolnymi godzinami ręcznie.
5. Tydzień zaczyna się w poniedziałek, strefa czasowa Europe/Warsaw, godziny zmian liczone w czasie lokalnym z uwzględnieniem zmiany czasu.
6. Menedżer też może mieć profil pracownika (np. kierownik na umowie o pracę w grafiku).
7. Rejestracja firmy możliwa bez kodu; firma dostaje wtedy 30 dni okresu próbnego (decyzja Piotra z 12.11.2026, 13.11.2026 wydłużone z 14 dni; zob. sekcja 14), potem jest tylko do odczytu, dopóki nie wpisze kodu.
8. Odświeżanie wyniku generowania przez odpytywanie co 1–2 s, bez websocketów.
9. CI na GitHub Actions (ruff, pytest, eslint, typecheck, build) to część stosu narzędzi, nie aplikacji; dodam w etapie 1, jeśli się zgadzasz.
10. Row Level Security w Postgresie odłożone; izolacja w warstwie aplikacji z testami.

## 8. Uwagi na kolejne etapy (z przeglądu etapu 2)

- Usuwanie a historia (od etapu 2 pilnuje tego baza, `on_delete=RESTRICT`): nie da się usunąć pojedynczo lokalu z okresami grafiku, okresu z wersjami, stanowiska użytego w zmianach ani pracownika z przypisaniami. Usunięcie całej firmy (tylko superadmin, np. firma testowa) nadal usuwa wszystko. Etap 7: pracownika wyłącza się przez `is_active = false`, a lokal archiwizuje (nowe pole przy ekranach), zamiast usuwać.
- Etap 7 (zrobione): lista zasad lokalu pokazuje, które zasady są dziedziczone z grupy, a które zmienione lub wyłączone w lokalu.
- Etap 3: zmiana numeru telefonu pracownika robi superadmin w panelu (historia zostaje, bo jest przypięta do konta, nie do numeru); zaproszenia oczekujące na stary numer trzeba wysłać ponownie. Numery spoza Polski: poza prototypem.
- Etap 6/7 (z przeglądu etapu 3): na ekranie zaproszeń menedżer widzi podpowiedź "Powiedz tej osobie, żeby zalogowała się tym numerem" (SMS z zaproszeniem nie idzie) oraz informację, że zaproszona osoba pracuje już w innym lokalu firmy i zachowa tamten lokal domowy. Komunikat trybu tylko do odczytu rozróżnia firmę bez kodu od firmy po wygaśnięciu. W trybie tylko do odczytu pracownik nadal widzi swój opublikowany grafik.
- Etap 7/8 (z przeglądu etapu 4): przy wyniku dla umowy o pracę krótka uwaga, że sprawdzenie Kodeksu pracy jest uproszczone (doba = dzień kalendarzowy, tydzień od poniedziałku) i nie zastępuje oceny prawnej; przy zasadzie "Cel godzin" z "bez wyjątków" napis "do 10 % odchylenia"; zasady bez niczego do oceny pokazane jako "nic do oceny", a prośby "inne" jako "do oceny przez kierownika" obok procentów; zmiany pożyczonych osób widoczne w grafiku lokalu, który je przyjmuje. Do sprawdzenia z pilotem: czy równy podział weekendów ma też wyłapywać osoby bez żadnej zmiany (dziś pomija je, łapie je tylko cel godzin).
- Decyzje Piotra po przeglądzie etapu 5 (12.11.2026): każdy lokal generujemy osobno, lokale są niezależne, chyba że kierownik w poleceniu powie inaczej; daty okresu wpisuje kierownik, razem z dniem układania grafiku, i może jednym przyciskiem poprosić wszystkich pracowników o dyspozycje (etap 7: przycisk, etap 9: powiadomienie); ponowne generowanie usuwa nieprzypięte ręczne poprawki (etap 8: uprzedzić o tym przy przycisku), a zmiany w wyniku kierownik wprowadza poleceniem do asystenta; generator ma być w pełni ustawialny poleceniami (etap 10 obejmie też polecenia kierownika, nie tylko prośby pracowników).
- Do sprawdzenia z pilotem (z przeglądu etapu 6): czy pracownicy rozumieją, że "chętnie" z godzinami blokuje inne zmiany tego dnia (krótki test z 3–5 osobami); kierownik nie chce twardego zamknięcia dyspozycji w terminie, tylko oznaczenia "zmienione po terminie" w siatce (decyzja Piotra z 12.11.2026, zrobione w etapie 7).
- Do sprawdzenia z pilotem: porównanie jakości z grafikami układanymi ręcznie. Etap 7/8: prośby "inne" i przypięcia wyraźnie widoczne na ekranie.
- Przed wdrożeniem dla prawdziwych użytkowników: bramka SMS (bez niej kody logowania są w logach serwera; `manage.py check` ostrzega: `accounts.W001`), sprawdzenie limitu 20 próśb o kod na adres IP przy wspólnym Wi-Fi w lokalu. (Okres próbny dla firmy bez kodu: rozstrzygnięte w etapie 8, 30 dni.)

## 9. Etap 3: jak to działa i przyjęte założenia

- Logowanie: `apps/accounts/login.py`. Kod 6 cyfr z `secrets`, w bazie skrót HMAC (klucz z `SECRET_KEY`), 5 minut, 5 prób na kod. Limity liczone z tabeli `LoginCode` pod blokadą na numer i na adres IP (`pg_advisory_xact_lock`), więc dwa równoległe żądania nie ominą limitu. Konto powstaje przy pierwszym poprawnym kodzie.
- Wysyłka: `settings.SMS_BACKEND` (ścieżka do klasy z metodą `send`). Domyślnie `ConsoleSmsSender` wypisuje SMS w logu serwera. Prawdziwa bramka to nowa klasa i zmienna środowiskowa.
- Adres IP klienta: za Caddym z nagłówka `X-Forwarded-For` (`DJANGO_NUM_PROXIES=1` w Docker Compose), bez proxy z połączenia.
- Wszystkie endpointy wymagają sesji (domyślne `auth=django_auth` w `config/api.py`, ze sprawdzaniem CSRF), poza `health`, `auth/*` i `GET /me`. Endpointy logowania sprawdzają CSRF same.
- Endpointy adresowane samym id obiektu (`/locations/{id}/…`, `/invitations/{id}/cancel`) ustalają firmę z obiektu przez `context_for(request, Model, id)`; obca firma dostaje 404.
- Tryb tylko do odczytu: `ctx.require_writable()` w każdym endpoincie zmieniającym dane firmy (402). Stan subskrypcji liczy `apps/billing/services.py::subscription_state`.
- Kody dostępu: admin → Kody dostępu → Dodaj otwiera stronę generowania partii (1–100 kodów); kody widać raz.
- Stare kody logowania usuwa codzienne zadanie okresowe workera (`accounts.delete_old_login_codes`).

Założenia:
1. Ekrany logowania, zaproszeń i subskrypcji powstają w etapie 6 (po akceptacji kierunku wizualnego); etap 3 dostarcza API, testy i wygenerowanego klienta.
2. Osoba, która już pracuje w innym lokalu tej samej firmy i przyjmie zaproszenie pracownika do kolejnego, zachowuje dotychczasowy lokal domowy.
3. Zaproszenie na rolę menedżera przyjęte przez pracownika podnosi rolę do menedżera i zostawia profil pracownika.
4. Odpowiedź na zaproszenie (akceptacja, odrzucenie) działa także wtedy, gdy firma jest w trybie tylko do odczytu; nowych zaproszeń wysłać wtedy nie można.
5. Stan subskrypcji i kody widzi właściciel i menedżer firmy; pracownik widzi tylko, czy firma jest w trybie tylko do odczytu (`GET /me`).
6. `ConsoleSmsSender` zostaje domyślny także poza trybem deweloperskim, dopóki nie ma bramki; kody logowania są wtedy w logach serwera, więc przed wdrożeniem dla prawdziwych użytkowników trzeba podłączyć bramkę.

## 10. Etap 4: silnik (`engine/`) i przyjęte założenia

- `engine/problem.py`: `Problem` i dane wejściowe (`Employee`, `Slot`, `Availability`, `Request`, `RuleConfig`, `WeightProfile`, `ExternalShift`). Niezmienne dataclasses z identyfikatorami jako tekst; `Problem` sprawdza spójność (nieznane osoby, zasady spoza katalogu, slot poza okresem) i rzuca `ProblemError`. Grafik to słownik `slot_id -> employee_id | None`.
- `engine/validator.py`: `validate(problem, schedule) -> ValidationReport` z naruszeniami twardymi (komunikaty po polsku dla menedżera), listą dziur, stopniem naruszenia (0–1) każdej zasady i każdej prośby, liczbą zmian względem opublikowanej wersji i godzinami osób. Nie rzuca wyjątków dla złego grafiku. Kod jest osobny od solvera i będzie też obsługiwał endpoint walidacji ręcznej edycji.
- `engine/scoring.py`: `score(problem, report, location=None)` daje trzy wartości (dziury, "zasady menedżera" %, "prośby pracowników" %) dla całości albo jednego lokalu; `penalty()` to cel fazy 2 generatora, w punktach: `manager_share × (100 − zasady %) + (1 − manager_share) × (100 − prośby %) + stability_penalty × liczba zmian`.
- Testy silnika (`backend/tests/engine/`) nie potrzebują bazy: `DJANGO_DEBUG=1 uv run pytest tests/engine`.

Założenia:
1. Czas: zmiana należy do dnia, w którym się zaczyna (także nocna). Długości i przerwy liczone w czasie rzeczywistym (UTC), więc nocka 22–06 w noc zmiany czasu trwa 7 h (marzec) albo 9 h (październik). Godzina, której nie ma (02:30 w marcu), przesuwa się na 03:30; godzina podwójna (02:30 w październiku) to jej pierwsze wystąpienie.
2. Umowa o pracę, uproszczenia zgodne ze spec (doba pracownicza i okres rozliczeniowy później): 11 h odpoczynku między końcem zmiany a początkiem następnej (dokładnie 11 h wystarcza, 10 h 59 min nie); najwyżej 8 h łącznie w zmianach zaczynających się danego dnia kalendarzowego; 35 h nieprzerwanego wolnego w każdym tygodniu kalendarzowym (pon. 00:00 – pon. 00:00 czasu lokalnego), sprawdzane w tygodniach, w których osoba ma zmianę z tego grafiku.
3. Zmiany stykające się (06–14 i 14–22) nie nachodzą na siebie; dla zlecenia to poprawny grafik, dla umowy o pracę łamie 11 h odpoczynku i 8 h na dobę.
4. Zmiany spoza okresu (poprzedni okres, inny lokal) przekazuje warstwa Django jako `ExternalShift`; liczą się do nakładania, odpoczynku, 8 h na dobę i dni z rzędu, nie do godzin miesięcznych.
5. Dyspozycyjność: wpis bez godzin dotyczy każdej zmiany zaczynającej się tego dnia. Wpis z godzinami: "nie mogę" i "wolę nie" dotyczą zmian nachodzących na ten zakres (styk się nie liczy), "chętnie" tylko zmian mieszczących się w zakresie.
6. Prośby z kalendarza: każdy dzień "wolę nie" to osobna pozycja o wadze poziomu "ważne", ale pełną wagę mają najwyżej 2 dni na tydzień okresu na osobę; kto zaznaczy więcej, ma tę samą łączną wagę rozłożoną na wszystkie dni (zaznaczenie całego miesiąca nie przeważy kolegów); dni "chętnie" jednej osoby to jedna pozycja o wadze "mile widziane", liczona jako udział dni pracy przypadających na dni "chętnie" (spośród tylu dni, ile się da). Osoba bez zmian nie łamie "chętnie".
7. Prośby tekstem: unikaj osoby / preferuj osobę = udział zmian prośbodawcy, na których ta druga osoba pracuje w tym samym lokalu w tym samym czasie; typ zmiany = udział zmian innego typu (albo tego typu przy "nie chcę"); limit godzin = nadwyżka / limit; "inne" nie są oceniane. Waga = waga poziomu × korekta menedżera (ważniejsza ×2, mniej ważna ×0,5). Odrzucone prośby nie trafiają do `Problem`.
8. Zasady liczone per lokal: zasady dotyczące osoby (odpoczynek, dni z rzędu, godziny, pora w tygodniu, zmiany w tygodniu) dla osób z tym lokalem domowym, zasady dotyczące zmian (zamknięcia, pora stanowiska) dla slotów tego lokalu. Stopień naruszenia zasady = udział miejsc, w których jest złamana (np. par kolejnych zmian, dni pracy, tygodni osoby), albo dla godzin średnie względne odchylenie.
9. Równy podział weekendów i zamknięć: osobno dla każdego stanowiska, porównujemy osoby z tym stanowiskiem, które mają w okresie choć jedną zmianę; różnica 1 jest w porządku. Zasada "bez wyjątków" = różnica najwyżej 1.
10. Cel i maksimum godzin miesięcznych są proporcjonalne do części miesiąca objętej okresem (tydzień listopada = 7/30 celu). Cel godzin "bez wyjątków" dopuszcza odchylenie 10 %.
11. Ocena: zasady "bez wyjątków" nie wchodzą do procentów (to ograniczenia), tak samo zasady bez niczego do zmierzenia (np. równe zamknięcia, gdy nie ma zmian zamykających); `Scores` podaje ich liczbę (`unmeasured_rules`) oraz liczbę próśb "inne" zostawionych menedżerowi (`unscored_requests`), żeby 100 % nie wyglądało na "wszystko sprawdzone". Waga zasady wynika z miejsca wśród zasad miękkich lokalu: 1, `rank_decay`, `rank_decay²`… Brak pozycji w grupie = 100 %.
12. `stability_penalty` w profilu wag oznacza punkty skali 0–100 za każdą zmianę opublikowanego przypisania (domyślnie 5).
13. Pożyczenie osoby do innego lokalu nie jest błędem walidatora (robi je menedżer ręcznie); ograniczenie do lokalu domowego dotyczy tylko generatora.

## 11. Etap 5: generator i przyjęte założenia

- `engine/solver.py`: `solve(problem, time_limit_s, workers, seed, weights=None, diversity_from=())` buduje model CP-SAT z tego samego `Problem` co walidator. Faza 1 minimalizuje dziury (40 % limitu czasu; na danych demo dowód optimum w ok. 1–2 s), faza 2 przy tej liczbie dziur minimalizuje karę z `engine.scoring.penalty`, z podpowiedzią z fazy 1. Każda zasada z katalogu ma metodę `_rule_<kod>`: dla "bez wyjątków" ograniczenie, dla zwykłej kara.
- Kara w modelu odwzorowuje ocenę walidatora: dokładnie dla dni "wolę nie", próśb tekstem (poza mianownikiem udziału), celu i maksimum godzin, dni z rzędu, osoby odpowiedzialnej na zamknięciu, równego podziału (dzielenie w modelu) i stabilności. Zasady liczone jako udział w zmiennej liczbie miejsc (odpoczynek, ta sama pora w tygodniu, zmiany w tygodniu, stała pora stanowiska) i "chętnie" dzielą przez oszacowanie tej liczby. Menedżer zawsze widzi ocenę z walidatora, nie wartość z modelu.
- Gdy model nie ma rozwiązania: najpierw walidator sprawdza same przypięcia i dni minione (np. przypięta osoba ma "nie mogę"), potem generator po kolei wyłącza zasady "bez wyjątków" i nazywa te, bez których grafik da się ułożyć (najwyżej 2 s na zasadę i łącznie nie dłużej niż limit czasu generowania).
- `apps/scheduling/problem_builder.py` czyta bazę do `Problem`, `apps/scheduling/generation.py` przyjmuje zlecenie (API), wykonuje je (worker) i zapisuje szkic, `apps/scheduling/tasks.py` to zadania kolejki. Endpointy: `GET/POST /locations/{id}/periods`, `POST /periods/generate`, `GET /generation-runs/{id}`.
- Docker Compose ma osobny kontener `solver` (kolejka `solver`, `SOLVER_CONCURRENCY=1`, max 2) obok `worker` (kolejka `default`). `SOLVER_WORKERS` = liczba wątków CP-SAT na jedno generowanie (domyślnie 8).
- `manage.py generate_schedule --company <id>` albo `--period <id>` układa grafik od razu, bez kolejki i bez liczenia do limitu (do sprawdzania na danych demo). Dane demo (4 piekarnie, miesiąc, razem 1015 zmian, 76 osób), każda piekarnia osobno po 30 s: razem 19 dziur (minimum, wynika z dyspozycji), zasady menedżera ok. 89–91 %, prośby ok. 88–92 %. Przy `SOLVER_CONCURRENCY=1` cztery lokale układają się po kolei, ok. 2 minut; przy 2 ok. minuty.

Założenia:
1. Sloty powstają z obsady dnia tygodnia, a wyjątek na datę zastępuje ją dla tej pary (zmiana, stanowisko); wyjątek bez godzin zostawia zwykłe godziny. Zmiana "dowolne godziny" bez godzin w obsadzie i w wyjątku zatrzymuje generowanie z komunikatem, co uzupełnić (pominięcie ukryłoby całą nieobsadzoną zmianę, bo nie byłoby nawet dziury; uwaga z przeglądu PR #6).
2. Każdy lokal generujemy osobno: `POST /periods/generate` z kilkoma okresami zakłada osobne zlecenie dla każdego (każde liczy się do limitu). Lokale mają wtedy własne zasady i profil wag, a okresy mogą mieć różne daty. Silnik nadal umie ułożyć kilka lokali w jednym modelu, na wypadek gdyby kierownik w poleceniu powiązał lokale (etap 10).
3. Kolejność zasad lokalu: zasady grupy i lokalu w jednej liście według pola "miejsce na liście"; przy tym samym miejscu zasada lokalu jest wyżej; ustawienie lokalu dla tej samej zasady zastępuje ustawienie grupy, a wyłączone zasady wypadają. Profil wag: własny profil lokalu, a bez niego profil grupy, a bez obu wartości domyślne.
4. Prośby tekstem: tylko zinterpretowane trafiają do generatora jako swój typ; nowe, niejasne ("do decyzji menedżera") i dotyczące osoby spoza grafiku są typu "inne" (liczone jako "do oceny przez kierownika"); odrzucone pomijamy.
5. Ponowne generowanie, gdy okres ma opublikowaną wersję: dni przed dzisiejszym są zamrożone i biorą zmiany z opublikowanej wersji (także gdy ustawienia obsady się zmieniły); dalsze dni układamy z obecnej obsady z karą za każdą zmianę względem opublikowanej. Przypięcia bierzemy z najnowszej wersji okresu (szkicu albo opublikowanej).
6. Osoba wyłączona (`is_active = false`) albo pożyczona z innego lokalu zachowuje tylko swoje przypięte i minione zmiany; generator nie daje jej nowych. Opublikowane zmiany tych samych osób w innych okresach i lokalach (7 dni wokół okresu) liczą się do odpoczynku, nakładania i dni z rzędu.
7. Wynik zapisujemy jako nową wersję szkicu (numer o 1 większy) dla każdego lokalu; okres "zbieranie dyspozycji" przechodzi w "szkic". Historię przypisań (`AssignmentEvent`) zapisujemy dopiero przy publikacji (etap 8), żeby kolejne szkice jej nie zaśmiecały.
8. Limit generowań liczymy przy zleceniu (blokada na wierszu firmy, więc dwa równoczesne zlecenia go nie przekroczą); nieudane generowanie (brak zmian, sprzeczne zasady, błąd, przekroczony czas bez wyniku) oddaje użycie. Drugie zlecenie dla okresu, który już się układa, dostaje 409.
9. Zlecenie, które zostało "w trakcie" ponad 10 minut (albo "w kolejce" ponad 30), zadanie okresowe co 10 minut oznacza jako nieudane, żeby ekran nie czekał w nieskończoność.
10. Warianty: kod przyjmuje inny profil wag i listę wcześniejszych grafików, od których nowy musi się różnić w min. 15 % przypisań; w tej wersji wołamy go raz.

## 12. Etap 6: wygląd i ekrany pracownika

- Kierunek wizualny "kartka z zaplecza" zaakceptowany przez Piotra 12.11.2026 (podgląd: https://claude.ai/artifact/1oXFa1qyj6754qT9KLoKrx). Tokeny: `frontend/src/styles/tokens.css` (blok `@theme` Tailwinda z wyłączonymi domyślnymi kolorami, rozmiarami pisma, promieniami i cieniami, więc klasy spoza tokenów nie istnieją). Krój Atkinson Hyperlegible Next z paczki `@fontsource-variable` (bez zapytań do Google Fonts). Komponenty w stylu shadcn/ui: `src/components/ui/` (przycisk na `class-variance-authority`, panel na Radix Dialog).
- Ekrany: `/logowanie` (numer, potem kod: sześć pól, wpisanie szóstej cyfry loguje, odliczanie do ponownego wysłania), `/zaproszenia`, `/grafik` ("Mój grafik"), `/kiedy-moge`. Ekrany pracownika mają zakładki na dole na telefonie i u góry na komputerze, kolumna do 560 px. `/` kieruje do logowania, zaproszeń albo grafiku.
- "Kiedy mogę": pasek stanów ("pędzel") przyklejony do dołu ekranu, przeciąganie po dniach, zapis od razu po każdym ruchu, "Cofnij", "Godziny dnia" (panel z godzinami jednego dnia; otwiera go też stuknięcie w dzień, który już ma wybrany stan, i lista "Dni z godzinami" pod kalendarzem), "Więcej opcji" (powtarzanie co tydzień, kopiowanie z poprzedniego miesiąca), "Gotowe, wysyłam kierownikowi", "Coś jeszcze?" (prośby tekstem, interpretacja w etapie 10).
- Nowe endpointy pracownika (zawsze z `company_id`, na własnym profilu pracownika w tej firmie; bez profilu 404 z wyjaśnieniem): `GET /me/schedule`, `GET/PUT /me/availability`, `POST /me/availability/pattern`, `POST /me/availability/copy-previous`, `POST /me/availability/submit`, `GET/POST /me/requests`, `DELETE /me/requests/{id}`. `MyInvitationOut` podaje też, kto zaprasza.
- `manage.py generate_schedule ... --publish` od razu publikuje wynik, żeby na danych demo "Mój grafik" miał co pokazać (publikacja z ekranu menedżera w etapie 8).

Założenia:
1. Firma w adresach pracownika to parametr `company_id` (jedna osoba może pracować w kilku firmach); aplikacja zapamiętuje wybraną firmę na urządzeniu, a przy kilku firmach pokazuje wybór w nagłówku.
2. "Kiedy mogę" pokazuje najbliższy okres lokalu domowego w stanie "zbieranie dyspozycji". Zmieniać można tylko wtedy; po terminie, a przed rozpoczęciem układania, zmiany są nadal przyjmowane (termin jest informacją; zamyka dopiero generowanie). Termin = początek okresu minus `availability_deadline_days` lokalu.
3. "Powtarzaj co tydzień" zapisuje `AvailabilityPattern` i od razu wpisuje dni od początku okresu do wybranej daty (najwyżej rok), nadpisując wcześniejsze zaznaczenia tych dni tygodnia. "Skopiuj z poprzedniego miesiąca" bierze ten sam dzień tygodnia 4 tygodnie wcześniej (5, gdy 4 tygodnie wcześniej to nadal ten okres).
4. "Cofnij" zapisuje poprzedni stan dni; dzień bez wcześniejszego zaznaczenia wraca do "obojętnie" (wiersz zostaje, co dla generatora znaczy to samo co brak wiersza).
5. "Mój grafik" pokazuje opublikowane zmiany od dziś na 62 dni naprzód; suma godzin dla bieżącego miesiąca i każdego miesiąca z listy liczy wszystkie opublikowane zmiany tego miesiąca (także te, które minęły). "Z Tobą" to osoby z opublikowanego grafiku tego samego lokalu, których zmiana nakłada się na moją; na ekranie trzy imiona i liczba pozostałych.
6. Godziny dnia (prośba Piotra): zmienia się znaczenie godzin w silniku (`engine.problem.Availability`): "chętnie"/"obojętnie" z godzinami = tylko w tych godzinach, poza nimi "nie mogę"; koniec przed początkiem = do rana. Ograniczenie w bazie zmienione z "początek przed końcem" na "początek różny od końca".
7. Kierownik bez profilu pracownika, który wejdzie na ekrany pracownika, widzi komunikat, że nie jest pracownikiem; jego ekrany powstają w etapie 7.


## 13. Etap 7: ekrany menedżera

- Zasada produktowa (Piotr, 12.11.2026, spec.md punkt 6 menedżera): grafik powstaje tylko na świadome polecenie kierownika, po terminie dyspozycji albo przy komplecie. W kodzie nic nie układa grafiku samo; zadania okresowe workera to tylko sprzątanie kodów logowania i oznaczanie zawieszonych generowań jako nieudane.
- Ekrany (`frontend/src/features/manager/`, trasy `/kierownik/...`): "Lokale" (start kierownika: każdy lokal z okresem, terminem, paskiem "wpisali X z Y", listą osób bez dyspozycji, liczbą dni zmienionych po terminie, przyciskiem "Poproś o dyspozycje" / "Przypomnij (N)" i napisem "Można układać grafik", gdy termin minął albo wszyscy wpisali; archiwum lokali), a w lokalu karty "Dyspozycje" (okres i termin, siatka pracownicy × dni z godzinami i znakiem zegara przy zmianach po terminie, prośby tekstem z decyzją kierownika), "Pracownicy" (stanowiska, umowa, cel i maksimum godzin, wyłączenie z grafiku, zaproszenia), "Ustawienia lokalu" (dane lokalu, stanowiska, zmiany i godziny, tabela obsady, wyjątki na daty, archiwizacja) i "Zasady" (jedna lista do przeciągania albo strzałkami, przełącznik, "bez wyjątków", parametry, "z grupy" / "zmienione w tym lokalu", podgląd skutku przed zapisem). Zasady grupy: `/kierownik/grupa/{id}/zasady`.
- Nowe pola: `Location.archived_at`, `SchedulePeriod.availability_deadline` (dzień układania = ostatni dzień dyspozycji; puste = `availability_deadline_days` lokalu) i `SchedulePeriod.availability_requested_at`.
- Nowe endpointy: `GET /manager/overview?company_id=`, `POST /groups`, `POST /locations`, `GET/PATCH /locations/{id}` (także `archived`), `GET /locations/{id}/setup`, `POST /locations/{id}/positions`, `PATCH/DELETE /positions/{id}`, `POST /locations/{id}/shift-types`, `PATCH/DELETE /shift-types/{id}`, `PUT /locations/{id}/staffing` (cała tabela tygodnia), `POST /locations/{id}/staffing-exceptions`, `DELETE /staffing-exceptions/{id}`, `GET /locations/{id}/employees`, `PATCH /employees/{id}`, `PATCH /periods/{id}` (termin), `POST /periods/{id}/ask-availability`, `GET /periods/{id}/availability`, `GET /periods/{id}/requests`, `PATCH /requests/{id}`, `GET/PUT /scopes/{location|group}/{id}/rules`, `POST /scopes/{location|group}/{id}/rules/preview`.

Założenia:
1. "Zmienione po terminie" = dzień dyspozycji zapisany (`AvailabilityDay.updated_at`) od północy dnia po terminie, w strefie lokalu. Pracownik może zmieniać do ułożenia grafiku (decyzja Piotra).
2. "Poproś o dyspozycje" zapisuje powiadomienie w aplikacji (`Notification`, rodzaj `availability_requested`) dla każdego aktywnego pracownika lokalu; "Przypomnij" tylko dla tych bez "Gotowe". Pokazanie powiadomień pracownikowi to etap 9. Działa tylko w okresie "zbieranie dyspozycji".
3. Zasady lokalu: ekran wysyła całą listę po kolei. Zasada ustawiona dokładnie jak w grupie i na tym samym miejscu dalej idzie za grupą (bez wiersza lokalu); inaczej lokal zapisuje własne ustawienie (także gdy zmieniło się tylko miejsce na liście, bo kolejność całej listy jest jedna). Etykieta "z grupy" / "zmienione w tym lokalu" porównuje ustawienia, nie miejsce. Zasady z parametrem stanowiska lub zmiany ("Stała pora dla stanowiska", "Ktoś odpowiedzialny na zamknięciu") ustawia się tylko w lokalu. Nowy lokal bez grupy startuje z włączonymi zasadami dobrej praktyki.
4. Podgląd skutku zasad nie układa grafiku od nowa (solver działa tylko w workerze): sprawdza walidatorem ostatni grafik lokalu (opublikowany, a bez niego najnowszy szkic) z obecnymi i z nowymi zasadami i mówi, ile razy każda zmieniona zasada byłaby złamana, oraz jak zmieni się ocena "zasady kierownika". Bez ułożonego grafiku podgląd mówi, że nie ma na czym sprawdzić. Pełne "co by było" (np. ile próśb przestałoby być spełnionych po ponownym ułożeniu) może być zadaniem workera w etapie 8.
5. Obsada: dla zmian z dowolnymi godzinami ekran ustawia jedne godziny na cały wiersz (zmiana × stanowisko), choć API przyjmuje godziny na każdy dzień osobno. Usunięcie stanowiska użytego w ułożonym grafiku jest odrzucane (409), można zmienić nazwę; usunięcie zmiany zostawia ułożone grafiki (godziny są w nich skopiowane).
6. Lokal archiwizuje tylko właściciel; archiwalny lokal znika z listy i z generowania (409), historia zostaje. Grupę lokali zakłada i zmienia tylko właściciel.
7. Pracownika "wyłącza z grafiku" kierownik jego lokalu (`is_active = false`); jego dawne zmiany zostają.

Na etap 8 (dopisane tutaj, nie zrobione w etapie 7): przycisk "Ułóż grafik" przy lokalu, aktywny jako świadoma akcja, z podpowiedzią, gdy termin minął albo wszyscy wpisali (i ostrzeżeniem, ilu osób brakuje); "Ułóż dla wszystkich". Ekran rejestracji firmy i wpisania kodu dostępu (API jest od etapu 3) też nie powstał w etapie 7; do zrobienia razem z etapem 8 albo osobno.

Po przeglądzie Prelinta (PR #9): komunikat po "Poproś o dyspozycje" mówi, że pracownicy zobaczą powiadomienie w jednej z następnych wersji i że na razie trzeba im powiedzieć osobiście; podgląd zasad mówi wprost, że to sprawdzenie ostatniego grafiku, a nie prognoza; ekran zasad lokalu tłumaczy, kiedy zasada przestaje iść za grupą; licznik to "Wysłali dyspozycje" (przycisk "Gotowe"), nie zaznaczone dni. Do sprawdzenia w pilocie: czy kierownik chce móc pominąć zmiany po terminie, czy podgląd na ostatnim grafiku wystarcza, i czy ktoś poza właścicielem musi zakładać lokale i grupy.

## 14. Etap 8: układanie z ekranu, edycja, publikacja, godziny

- Decyzja Piotra (12.11.2026): firma założona bez kodu dostaje okres próbny (`Subscription.source = "trial"`, `TRIAL_DAYS` w ustawieniach, domyślnie 30). Najpierw 14 dni; 13.11.2026 Piotr zgodził się na 30 po uwadze Prelinta, że 14 dni nie mieści pełnego miesięcznego cyklu. Limit ułożeń grafiku działa też w okresie próbnym. Po nim tryb tylko do odczytu jak po wygaśnięciu kodu; baner i ekran "Dostęp" mówią, ile dni zostało.
- Ekrany: "Załóż firmę" (`/rejestracja`: numer, kod SMS, nazwa firmy, imię i nazwisko, opcjonalny kod; link z ekranu logowania), "Dostęp" (`/kierownik/dostep`: stan, ułożenia w miesiącu, wpisanie kodu), baner dostępu w panelu kierownika, "Godziny" (`/kierownik/godziny`: miesiąc, tabela osób z podziałem na lokale, CSV) i karta "Grafik" w lokalu (`/kierownik/lokal/{id}/grafik`). Na "Lokale" przycisk "Ułóż grafik" przy każdym lokalu i "Ułóż dla wszystkich" (każdy lokal osobno), z arkuszem, który ostrzega przed terminem, mówi, ilu osób brakuje i ile nieprzypiętych ręcznych poprawek zniknie; postęp odpytywany co 1,5 s.
- Karta "Grafik": trzy wartości oceny, twarde problemy, siatka dni × zmiany (przypięte, ręczne, pożyczone, bez obsady, "woli nie" oznaczone kolorem + ikoną + wzorem), przeciąganie osoby na inną zmianę z wynikiem sprawdzenia na żywo w trakcie przeciągania, arkusz zmiany z wyjaśnieniem (kto może, ile to kosztuje, kto nie może i dlaczego) i akcjami "Wpisz", "Zostaw bez obsady", "Przypnij", godziny osób, zasady z procentem, niespełnione prośby, wersje, "Opublikuj" i "Popraw grafik".
- Nowe pole `Assignment.manual` (ręczna zmiana). Nowy moduł `engine/explain.py` (bez Django): dla każdej osoby ze stanowiskiem sprawdza walidatorem grafik z tą osobą na zmianie, więc wyjaśnienie zgadza się z walidatorem. `apps/scheduling/editing.py`: sprawdzanie i zapis ręcznych zmian, przypinanie, poprawka opublikowanego grafiku, publikacja. Raport godzin: `apps/reports`.

Założenia:
1. Ręcznie można zmieniać tylko najnowszy szkic okresu. Opublikowany grafik poprawia się przez "Popraw grafik" (kopia jako nowy szkic), a starsze szkice dostają status "zastąpiony" przy nowym szkicu lub publikacji. Dni, które już minęły, są zamrożone (409).
2. Ręczna zmiana, która dodaje naruszenie twardej reguły, jest odrzucana (409 z powodem); miękkie skutki (np. ponad cel godzin) są pokazane jako ostrzeżenie, ale dozwolone. Zmieniona ręcznie zmiana traci przypięcie; "Przypnij" trzeba kliknąć osobno. Zmiana zostawiona bez obsady nie może być przypięta.
3. W edytorze można wpisać tylko osoby z lokalu (z danym stanowiskiem); pożyczanie z innych lokali zostaje dla oddawania zmian (etap 9).
4. Publikacja jest możliwa z dziurami (kierownik dostaje ostrzeżenie), ale nie z naruszeniem twardej reguły. Historia przypisań (`AssignmentEvent`) jest zapisywana przy publikacji, dla każdej zmienionej względem poprzedniej publikacji zmiany, z powodem "ręcznie" albo "ułożone". Publikacja zapisuje powiadomienie `schedule_published` dla pracowników lokalu (pokazanie to etap 9).
5. Okres próbny dostaje tylko pierwsza firma danej osoby; kolejne firmy bez kodu są od razu tylko do odczytu.
6. Wyjaśnienie zmiany liczy szybkie sprawdzenie walidatorem dla każdej osoby (ok. 5 ms na osobę). Głębsza analiza ("kto by mógł, gdyby przestawić inne zmiany") wymaga solvera w workerze i zostaje na później.
7. Raport godzin liczy tylko opublikowane zmiany w lokalach, którymi zarządza kierownik, w podanym miesiącu kalendarzowym (zmiana należy do dnia, w którym się zaczyna). CSV: średniki, przecinek dziesiętny, BOM, żeby Excel otworzył polskie znaki.


Po przeglądzie Prelinta (PR #10): nad siatką jest pasek "Ręczne poprawki bez przypięcia: N" z przyciskiem "Przypnij poprawki", bo ponowne układanie je usuwa; arkusz publikacji mówi, że powiadomień w aplikacji jeszcze nie ma (trzeba powiedzieć pracownikom), a przy poprawce opublikowanego grafiku wymienia osoby, których zmiany się zmieniają (`VersionOut.changed_people`); ekran "Godziny" mówi, że to plan z opublikowanych grafików w lokalach kierownika, a nie ewidencja czasu pracy, i oznacza osobę, która w tym miesiącu pracuje też w lokalach, których kierownik nie prowadzi (suma niepełna; w CSV kolumna "Uwagi"). Ręczna zmiana osoby w edytorze zawsze zdejmuje przypięcie (wyjątek od etapu 9: zatwierdzona oddana zmiana jest przypięta, bo to uzgodnienie trzech osób, a nie poprawka kierownika do przemyślenia). Link "Załóż firmę" zostaje w pustym stanie zaproszeń, bo to jedyna droga do rejestracji dla zalogowanej osoby bez firmy (np. kierownika, który najpierw się zalogował). Do sprawdzenia w pilocie: czy kierownik oczekuje, że ręczne poprawki zostają domyślnie, i czy potrzebuje obejścia „nie mogę” po rozmowie z pracownikiem.

## 16. Etap 9: oddawanie zmian, powiadomienia, historia przypisań

- Logika: `apps/marketplace/services.py` (oddanie, "Biorę", wycofanie, zatwierdzenie, odrzucenie, oddania po nowej publikacji), `apps/notifications/services.py` (zapis powiadomień i polskie zdania budowane przy odczycie z rodzaju i danych, więc poprawka tekstu działa też dla starych powiadomień).
- Ekrany: w "Mój grafik" przycisk "Oddaj" przy każdej zmianie (arkusz z wyjaśnieniem, że do decyzji kierownika to nadal moja zmiana, i "Zostaję na tej zmianie"), sekcja "Zmiany do wzięcia" z "Biorę" / "Jednak nie biorę"; trzecia zakładka "Powiadomienia" z licznikiem nowych (`/powiadomienia`); u kierownika "Oddane zmiany" (`/kierownik/oddane-zmiany`) z licznikiem chętnych w nagłówku; w arkuszu zmiany na karcie "Grafik" "Historia tej zmiany".
- Licznik i listy odświeżają się co minutę (bez websocketów, jak w założeniu 8 z sekcji 7).

Założenia:
1. Kto dostaje powiadomienie o oddanej zmianie: każda aktywna osoba firmy (z każdego lokalu) poza oddającym, która ma stanowisko o tej samej nazwie (stanowiska są per lokal, więc "Sprzedawca" w Wieliczce i "sprzedawca" w Skawinie to to samo; wielkość liter bez znaczenia) i dla której walidator nie znajduje nowego twardego problemu po wpisaniu jej na tę zmianę w opublikowanym grafiku: "nie mogę", inna zmiana w tym czasie (także w innym lokalu), zasady "bez wyjątków". Od PR #11 dzień bez zaznaczenia znaczy "mogę", więc "zaznaczyły dyspozycyjność" rozumiem jako "nie zaznaczyły nie mogę".
2. Sprawdzenie powtarza się przy "Biorę", na liście kierownika (przy każdym chętnym widać powód, dla którego już nie może) i przy zatwierdzeniu, bo grafik i kalendarz mogą się zmienić. "Zmiany do wzięcia" pokazują tylko oddania, które dana osoba może wziąć teraz.
3. Oddać można tylko własną zmianę z opublikowanego grafiku, która się jeszcze nie zaczęła. Oddanie zaczętej zmiany wygasa samo. Kierownik decyduje o chętnych w lokalach, którymi zarządza (właściciel o wszystkich); powiadomienie "ktoś chce wziąć" dostają właściciele i kierownicy tego lokalu.
4. Zatwierdzenie zmienia przypisanie w opublikowanej wersji w miejscu (bez nowej wersji; nowa wersja na każde oddanie zastąpiłaby albo zdublowała szkic, który kierownik może właśnie poprawiać, a zmianę i tak zapisuje historia przypisań), oznacza je jako ręczne i przypięte (ponowne układanie nie cofnie uzgodnionej zamiany) i "z innego lokalu", gdy biorący jest spoza lokalu. Jeśli okres ma nowszy szkic i ta osoba nadal jest w nim na tej zmianie, szkic też się zmienia. Historia: `AssignmentEvent` z powodem "oddana zmiana" i osobą, która zatwierdziła. Pozostali chętni dostają odmowę.
5. Osoba pożyczona z innego lokalu "ma" stanowisko lokalu, jeśli ma stanowisko o tej samej nazwie (`problem_builder`), więc grafik z taką osobą przechodzi walidator i daje się opublikować.
6. Nowa publikacja okresu: otwarte oddania idą za zmianą, jeśli oddający nadal na niej jest; w przeciwnym razie wygasają, a oddający i chętni dostają powiadomienie.
7. Otwarcie "Powiadomień" oznacza pokazane jako przeczytane; do następnego odświeżenia zostają oznaczone "Nowe". Oznaczanie działa też w trybie tylko do odczytu (dopisane do wyjątków w spec.md: inaczej licznik nowych nie dałby się wyzerować); oddawanie i branie zmian nie działa.
8. Pełne zamiany dwóch osób (`AssignmentEvent.Reason.SWAP`) nadal na później; model oddań i historia ich nie blokują.
9. Kierownicy lokalu dostają powiadomienie już przy oddaniu zmiany (z liczbą osób, które mogą ją wziąć; przy zerze wprost, że oddający nadal ma tę zmianę), żeby oddanie bez chętnych nie czekało po cichu do dnia zmiany.

Po przeglądzie Prelinta (PR #13), do sprawdzenia w pilocie: czy powiadomienie do całej firmy (w danych demo jedna zmiana trafiła do 34 osób) nie jest za głośne i czy nie lepiej najpierw lokal domowy, a po kilku godzinach reszta; czy nazwy stanowisk w lokalach naprawdę się pokrywają (jeśli nie, potrzebne jawne powiązanie stanowisk); czy potrzebne jest przypomnienie oddającemu i kierownikowi na dzień przed zmianą bez chętnych (dziś tylko powiadomienie przy oddaniu).

