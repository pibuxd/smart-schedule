# Grafikomat: plan techniczny prototypu

Plan do akceptacji przed pisaniem kodu aplikacji. Zakres i wymagania: [spec.md](spec.md).
Kod, nazwy w kodzie i commity po angielsku; teksty interfejsu po polsku.

## Ustalenia asystenta na okres grafiku (18.11.2026)

Zatwierdzone ustalenia dotyczą jednego okresu zbierania dyspozycji. Domyślnie jest to ostatni nieopublikowany okres, dla którego poproszono o dyspozycje; ekran okresu może otworzyć rozmowę z tym okresem wybranym jawnie. Bez takiego okresu ustalenia czekają bez przypisania. Rozmowa otwarta jawnie z niezgłoszonego jeszcze okresu zapisuje do kolejki oczekującej lokalu. Przydzielenie następuje dopiero przez „Poproś o dyspozycje”, także gdy istnieje inny aktywny okres. „Poproś o dyspozycje” atomowo przejmuje oczekujące ustalenia dla wskazanego okresu. Ponowienie prośby nie przenosi ustaleń z innych okresów.

Publikacja oznacza zestaw jako wykorzystany i usuwa go z domyślnej listy aktywnej, bez kasowania rozmowy, zasad lub poleceń. Regeneracja i korekty tego samego okresu używają jego zachowanego zestawu; nowy okres nie przejmuje wykorzystanych ustaleń. Nieudane generowanie, szkic ani samo rozpoczęcie układania nie zużywają zestawu. Tabela przy dyspozycjach pokazuje zasady i polecenia dla wybranego okresu.

Technicznie `AssistantRuleSet` przechowuje migawkę zasad katalogowych, zmienione kody, lokal, opcjonalny okres oraz datę wykorzystania. Polecenia o osobach i wiadomości wskazują zestaw. Stałe zasady lokalu/grupy pozostają bazą nowych zestawów; rozmowa zmienia wyłącznie zestaw okresu. Migracja zachowuje wcześniejsze polecenia i przypisuje wykorzystane do ostatniej publikacji po ich utworzeniu, a pozostałe do otwartego zbierania dyspozycji lub kolejki oczekującej. Wszystkie zapisy serializują się z publikacją przez blokadę firmy. Zakres firmy, lokalu i wybranego okresu sprawdzany jest na serwerze.

## Kopiowanie ustaleń i przekazanie odrzuconej prośby (18.11.2026)

- `GET /locations/{id}/agreements/previous?period_id=` zwraca to, co można skopiować z najnowszego wcześniejszego okresu z ustaleniami (`agreements.previous`, `agreements.copyable`). `POST /locations/{id}/agreements/copy` kopiuje wyłącznie wskazane kody zasad i identyfikatory poleceń do zestawu okresu docelowego (albo kolejki oczekującej, gdy o dyspozycje jeszcze nie poproszono), pod blokadą firmy i lokalu. Pusty wybór niczego nie zmienia; wybór spoza aktualnej oferty daje 409; opublikowany okres docelowy daje 409. `bind_pending` nadal niczego nie przenosi z innych okresów.
- UI: `CopyPreviousAgreements` w tabeli ustaleń okresu (dyspozycje i zasady), zwinięte, bez zaznaczonych pozycji.
- `PATCH /me/requests/{id}` z `understood: false` dla statusu `rejected` ustawia `needs_manager`, czyści interpretację i zapisuje `unread_reason="rejected"` (migracja `availability.0008`). Generator traktuje taki wpis jak każdą nieodczytaną prośbę (`RequestType.OTHER`, bez punktacji). Karta prośby kierownika opisuje powód.

## Asystent z dostępem do API (19.11.2026)

Zastępuje „Ograniczenie zakresu asystenta (18.11.2026)”. Zakres produktu: spec.md, „Asystent odpowiada na wszystko o Grafikomacie i lokalu”.

- `apps/assistant/tools.py`: lista narzędzi do odczytu dla roli (pracownik, kierownik). Każde narzędzie to istniejący endpoint `GET /api/...` (nazwa = operation id), wywołany w workerze przez `django.urls.resolve` z `RequestFactory` jako osoba, która napisała wiadomość (`request.user`). Uprawnienia sprawdza sam endpoint (`tenant_context`, `require_manager_of`), więc asystent widzi dokładnie to, co ta osoba w aplikacji; 403/404 wracają do modelu jako błąd narzędzia. Firma i lokal są wpisywane przez serwer, model wybiera tylko okres, wersję, zmianę, miesiąc i zawężenie (`date_from`, `date_to`, `person`) dla długich list. Z odpowiedzi znikają telefony i pola techniczne, a wynik ponad ok. 40 tys. znaków jest przycinany z jawną notatką.
- `llm.py` (droga przez Claude; od 21.11.2026 domyślnie OpenRouter z `final_answer` zamiast `output_config.format`, sekcja 30): pętla narzędzi na `messages.create` (najwyżej 6 rund, odpowiedź końcowa w `output_config.format` sprawdzana Pydantic). Narzędzia nie mają `strict`: API dopuszcza najwyżej 16 parametrów typu „albo” (`anyOf`, null) łącznie we wszystkich ścisłych schematach zapytania, a schemat odpowiedzi zużywa większość z nich; ze `strict` w narzędziach każde zapytanie kończyło się błędem 400 „Schema is too complex for compilation” (20.11.2026). Test pilnuje tego limitu. Zamiast `strict` serwer sam sprawdza argumenty każdego wywołania ze schematem narzędzia (`tools.argument_error`): nieznany klucz, brak wymaganego albo zły typ wraca do modelu jako błąd narzędzia i nie dociera do endpointu, bo endpoint pominąłby nieznany klucz i odpowiedział o wszystkich. Stały prompt systemowy i lista narzędzi idą przed zmiennym kontekstem, z `cache_control`. Prompt zawiera krótki przewodnik po ekranach dla roli, żeby asystent mówił, gdzie co zrobić. Myślenie modelu ma poziom `output_config.effort` z `ANTHROPIC_EFFORT`, domyślnie `low`: każda runda narzędzi to osobne wywołanie, a Claude Opus 5.5 zawsze myśli (domyślnie na poziomie `medium`), więc przy dwóch–trzech rundach płaciłoby się za to myślenie kilka razy. Uwaga: pomiar „ok. 40 s” z testu 20.11.2026, od którego zaczęła się ta zmiana, był błędem skryptu testowego (30 s czekania przed wysłaniem); naprawdę odpowiedź przychodziła po ok. 7 s, a po zmianie przychodzi po 3–18 s. `low` zostaje, bo odpowiedzi w teście były trafne. Prompt prosi o wszystkie potrzebne odczyty naraz, w jednej rundzie. Każda odpowiedź zostawia w logu workera jedną linię: czas, liczba wywołań, użyte narzędzia i tokeny wyjścia.
- Kierownik (`CommandPlan`): `topic=app|unrelated`, `reply` (odpowiedź modelu jest pokazywana; zamiast stałego „Po zatwierdzeniu zapiszę…”), plan zmian jak dotąd. Pod każdym planem z poleceniem o osobie aplikacja pokazuje jako pierwszą uwagę, że to preferencja bez gwarancji przydziału, więc słowa modelu nie czytają się jak obietnica zmiany. Pytanie i zmiana w jednej wiadomości działają razem. `unrelated` daje stałą odmowę aplikacji bez zmian. Zmiana zasady na wartość, która już obowiązuje, daje „To już jest ustawione: …”. Polecenie o dniach poza okresem ustaleń jest blokowane z wyjaśnieniem (nie zmieniłoby żadnego grafiku), a dni częściowo poza okresem są obcinane z notatką. Porównanie ze skutkiem liczy się na grafiku okresu ustaleń; bez niego na ostatnim opublikowanym (`preview_version(..., period)`).
- Pracownik (`EmployeeReply`): `topic=app|unrelated`, `answer`, `preferences` (0–3), `leave_to_manager`, `replaces_request`. Same pytania kończą się statusem `answered` z odpowiedzią. Preferencje dają `interpreted` (pierwsza w `interpretation`, kolejne w `interpretation["more"]`; generator robi z każdej osobną prośbę z id `<pk>`, `<pk>:2`, …). Część nie do zamiany na ustawienie albo `leave_to_manager` bez żadnej preferencji daje `needs_manager` z jasnym zdaniem dla pracownika; `leave_to_manager` obok zapisanych preferencji daje `interpreted` z `interpretation["partial"]`, uwagą dla pracownika i dopiskiem dla kierownika, że resztę czyta sam. Odpowiedź modelu dla pracownika jest w nowym polu `TextRequest.reply` (`MyRequestOut.reply`); opis wielu części ma też `part_summary` pierwszej części dla generatora. `cannot=true` przy datach daje `MyRequestOut.unmarked_days` (dni bez „nie mogę” w kalendarzu) i przycisk, który zapisuje je istniejącym `PUT /me/calendar`. `notes` mówią o sprzeczności z kalendarzem („Chętnie” w dniu, w którym prośba mówi o wolnym) i o zmianie, której stanowisko osoby nie ma.
- Limity pisania są od 20.11.2026 domyślnie wyłączone (Piotr): `TEXT_REQUESTS_PER_PERIOD`, `ASSISTANT_MESSAGES_PER_DAY` i `ASSISTANT_COMMANDS_MONTHLY_LIMIT` mają domyślnie 0, a 0 znaczy „bez limitu” (wcześniej 10, 40 i 400). Liczba większa od zera w `.env` włącza limit jak dotąd. `TEXT_REQUESTS_PER_PERIOD` liczy tylko `new`, `interpreted`, `needs_manager`; przy włączonym asystencie sprawdza go worker: nowa prośba ponad limit kończy się odpowiedzią z prośbą o usunięcie lub poprawkę starej, pytania działają dalej. `ASSISTANT_MESSAGES_PER_DAY` liczy wiadomości osoby na dobę (wszystkie statusy). `ASSISTANT_COMMANDS_MONTHLY_LIMIT` liczy polecenia firmy w miesiącu, pytania też.
- Limit godzin prośby i polecenia może dotyczyć dnia (`hours_period=day`, `Request.daily_hours`): okna w `Request.hour_windows` to pojedyncze dni, więc walidator i solver liczą to samo.
- Zadanie okresowe `assistant.fail_stale_messages` (co 10 minut): wiadomość pracownika w stanie `new` lub polecenie `queued` starsze niż 15 minut przechodzi w `needs_manager`/`failed` (kierownik może dać prośbę asystentowi ponownie), żeby nic nie stało w „asystent czyta” bez końca.
- „Przekaż kierownikowi” i „Niech przeczyta kierownik” wysyłają kierownikom lokalu powiadomienie `request_for_manager`. Przekazana odpowiedź na pytanie ma w `assistant_misses` powód `forwarded_answer`: w pilotażu widać, jak często kierownik dostaje zwykłe pytania zamiast próśb.
- Kolumna `assistant_answer` zapisuje też listę wywołanych narzędzi (`tools`), żeby `assistant_misses` pokazywał, czego asystent szukał.
- Wyniki narzędzi mają przy każdej dacie dzień tygodnia (`weekday`), a godziny zmian są w czasie lokalu (`start_time`/`end_time`), żeby model niczego nie przeliczał sam. W panelu administratora listy próśb i poleceń pokazują odpowiedź asystenta (`reply`), żeby w pilotażu przejrzeć próbkę prawdziwych odpowiedzi (pomyłki w danych, słowa brzmiące jak obietnica przydziału).

## Wysuwany czat i okienko ustaleń (18.11.2026)

- `components/ui/drawer.tsx`: panel z prawej na Radix Dialog w trybie niemodalnym (bez tła, kliknięcie obok go nie zamyka). `features/manager/AssistantDrawer.tsx` trzyma jeden czat (od 22.11.2026 na cały panel kierownika, sekcja niżej), a `useAssistantDrawer().openChat({ locationId, periodId, text })` otwiera go z dowolnego ekranu, opcjonalnie z wpisanym początkiem wiadomości. Na ekranie od 1280 px treść strony odsuwa się, żeby okienko ustaleń było widać obok rozmowy.
- Trasa `/kierownik/lokal/$locationId/asystent` pokazuje teraz okienko ustaleń (`AssistantRulesTable`), zakładka nazywa się „Ustalenia”. To samo okienko jest przy dyspozycjach okresu i (skrócone) na ekranie zasad.
- Nowy endpoint `DELETE /locations/{location_id}/agreed-rules/{code}?period_id=` (`revert_agreed_rule`): zasada ustalona w rozmowie wraca do bieżącego ustawienia lokalu i znika z `changed_codes`; 404, gdy zasady nie ma wśród ustaleń, 409 po publikacji. Kolejność i usuwanie poleceń korzystają z istniejących endpointów.
- Pracownik: `RequestsSection` to okienko „Twoje prośby” (statusy `interpreted` i `needs_manager`, edycja i usuwanie istniejącymi endpointami) oraz ten sam `Drawer` z historią rozmowy i polem pisania. Bez zmian w API.
- Założenie: rozmowa pracownika zostaje jednokrokowa (jedna wiadomość, jedno odczytanie; poprawka zastępuje wcześniejszą prośbę). Wieloetapowe dopytywanie pracownika wymagałoby zmian w `interpret_request` i nie jest częścią tego etapu.

## Przycisk asystenta na każdym ekranie (22.11.2026)

- `components/assistant/AssistantFab.tsx`: okrągły przycisk w prawym dolnym rogu (`fixed`, `z-30`, pod arkuszami i panelem z `z-40`/`z-50`), cień `--shadow-fab`. Podpis od `lg` u pracownika, od 1600 px u kierownika (`nameFrom="wide"`), bo dopiero wtedy mieści się na marginesie obok treści.
- Kierownik: `AssistantDrawerProvider` przeniesiony z `LocationLayout` do `routes/kierownik.tsx` (klucz = firma). `LocationLayout` zgłasza swój lokal przez `useChatLocation(id)` (null dla archiwum) i nadal ma w nagłówku `OpenAssistantButton locationId`; czat bierze lokal z ekranu, potem ostatnio wybrany (`openChat({ locationId })` też go ustawia), a przy jednym lokalu jedyny z `GET /api/manager/overview`. Okres i szkic z `openChat` dotyczą tylko lokalu, dla którego je podano. Przy kilku lokalach (`overview.locations.length > 1`) nad rozmową wiersz „Lokal: nazwa”. `main` ma `pb-24`, pasek zapisu zasad `pr-20` na telefonie.
- Pracownik: `features/availability/EmployeeChat.tsx` (`EmployeeChatProvider` w `routes/_pracownik.tsx`) trzyma jeden `Drawer` z rozmową (`RequestsChat`); `RequestsSection` to już tylko okienko „Twoje prośby” i zgłasza swój miesiąc przez `useScreenChatScope`. Bez ekranu „Kiedy mogę” czat bierze okres z `GET /api/me/availability` (osobny klucz zapytania z dopiskiem `chat`, żeby nie zmieniać `gcTime: 0` ekranu kalendarza; odświeżany przy otwarciu), a bez okresu bieżący miesiąc. Opis panelu mówi, dokąd trafi prośba (`scopeLine`: „Prośby na grudzień 2026.”). `EmployeeChatTab` to czwarta zakładka paska na telefonie (`md:hidden`); od `md` przycisk w rogu. Niewysłany tekst czatu trzyma provider, osobno dla każdej rozmowy.
- Bez zmian w API.

## Czat asystenta (18.11.2026)

- Nowa trasa `/kierownik/lokal/$locationId/asystent`, dostępna z zakładek lokalu i zasad. Rozmowa oraz osobny panel przyjętych poleceń; na małym ekranie przełączanie między nimi. Istniejące kolory i typografia, lżejsze obramowania, wyraźny podział nadawców i pole pisania na dole.
- GET `/locations/{location_id}/assistant-commands` zwraca ostatnie 50 wpisów aktualnego autora w lokalu chronionym uprawnieniami, od najstarszego do najnowszego. W historii nie ma wiadomości innych kierowników ani innych firm. Bez nowego modelu rozmów i bez przechowywania treści w localStorage.
- Wspólne elementy rozmowy i edytora dla kierownika i pracownika. Polling tylko podczas oczekiwania, stan wydłużonego oczekiwania z ponownym odczytem, przewijanie do nowych odpowiedzi bez odrywania od czytanej historii. Przyciski zmieniające dane respektują tryb tylko do odczytu.
- Przegląd produktu: limit pamięci (od 20.11.2026 tylko w „Jak działa asystent”, nie pod polem pisania) i oznaczenia wpisów poza zakresem (ostatnie 6 zakończonych wpisów z 24 h; od 20.11.2026 `context.MAX_CONVERSATION` = 10 ostatnich, bez limitu czasu, u kierownika i pracownika). API zwraca `expires_at`; `can_apply` i zatwierdzenie sprawdzają ważność 24 h od `created_at`, także w transakcji zapisu. Bez nowego statusu lub migracji; wygasła propozycja zostaje w historii i pozwala wstawić treść do ponownego wysłania. Dotychczasowe kontrole osób, zmian i usuwanych poleceń pozostają aktywne. Efekty są historycznym porównaniem, nie bieżącym podglądem.
- Zasady pokazują przyjęte polecenia o osobach i ich kolejność. Zakładki zawijają się na małym ekranie, link powrotny jest zawsze widoczny. Edytor pracownika ma osobną etykietę wysyłki i nie wysyła Enterem; zwykłe statusy wyświetlane są bez awatara asystenta.
- Testy: zakres historii, trwałość widoku po ponownym wejściu, kolejne wiadomości i zatwierdzenia, obsługa błędów i klawiatury. Sprawdzenie widoku na komputerze i telefonie.

## Uzupełnienie etapu 10 po QA (18.11.2026)

- `chce_pracowac` przechowuje opcjonalne `shift_type`; solver i validator liczą tylko pasujące zmiany. Walidacja nie dopuszcza planu po utracie części danych. Komunikaty o zapisie wynikają ze sprawdzonego planu, a prośby mają opis zbudowany ze sprawdzonej struktury.
- Historyczny moduł kontekstu odczytu (obecnie nieprzekazywany modelowi) ogranicza zakres do firmy, lokalu i roli. Obejmuje maksymalnie 6 okresów od bieżącego miesiąca, ostatni szkic i publikację, limity liczby wierszy z jawnym oznaczeniem obcięcia. Godziny liczy aplikacja w UTC. Pracownik nie otrzymuje szkiców, ocen doświadczenia ani cudzych prywatnych próśb/dyspozycji.
- `TextRequest.status` otrzymuje `answered` (odpowiedź informacyjna) i `superseded` (zastąpiona). `supersedes` wskazuje poprzednią prośbę. Odpowiedzi i zastąpione wpisy są wyłączone z problemu generatora i aktywnej listy kierownika. Edycja zastąpionej prośby jest blokowana, aby nie wskrzesić jej przypadkiem.
- LLM wskazuje korektę przez numer z migawki własnych wcześniejszych próśb. Worker sprawdza zakres, status i `updated_at`, blokuje bieżący i poprzedni wpis w transakcji oraz zapisuje oba stany razem. Obca, nieznana, zmieniona lub już zastąpiona prośba nie może być usunięta z działania przez korektę. Dane menedżerskie poprzedniej prośby pozostają w mocy.
- Historia kierownika: maks. 10 wcześniejszych zakończonych wiadomości tego samego autora w lokalu i okresie ustaleń, bez limitu czasu (do 20.11.2026: 6 z 24 h). Nieprzyjęta propozycja nie jest obowiązującym ustawieniem.
- Przy `answered` pracownik ma przycisk „Przekaż kierownikowi”: istniejący PATCH `understood=false` zmienia stan na `needs_manager`, zachowując treść wiadomości.
- Testy regresyjne: konkretna zmiana w żądaniu pracy, solver i validator, częściowo nieobsługiwany plan, odczyt i izolacja danych, informacyjne odpowiedzi, korekty z zachowaniem audytu, wyścig z edycją i decyzje kierownika. Testy komponentów sprawdzają nowe stany i uczciwe potwierdzenia.

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
                                                      asystent (OpenRouter albo Claude API)
```

Kontenery Docker Compose: `caddy`, `api`, `worker`, `db`. Lokalnie do tego tryb deweloperski: Vite dev server z proxy `/api` do Django.

### Układ repozytorium

```
backend/
  config/                 ustawienia Django, urls, api (NinjaAPI)
  apps/
    accounts/             User (numer telefonu), logowanie kodem SMS, sesje, limity
    tenancy/              Company, LocationGroup, Location, Membership, Invitation, izolacja firm
    billing/              Subscription, AccessCode, CodeRedemption
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

### Ustawienia lokalu i pracownicy

| Model | Pola | Uwagi |
|---|---|---|
| `Position` | location, name | np. Sprzedawca, Piekarz, Kierownik zmiany; stawki w `pay.PositionRate` (sekcja 35) |
| `ShiftType` | location, name, start_time, end_time, kind (fixed/flexible), is_closing | koniec przed początkiem = przez północ |
| `StaffingRule` | location, weekday, shift_type, position, count, start/end (tylko dla zmian z dowolnymi godzinami) | unikalne (location, weekday, shift_type, position) |
| `StaffingException` | location, date, shift_type, position, count, start/end (opcjonalnie inne godziny) | np. Wigilia, dzień bez obsady (count=0) |
| `EmployeeProfile` | membership, home_location, positions (M2M), experience (1 początkujący / 2 samodzielny / 3 doświadczony), max_hours_month, target_hours_month, is_active | zlecenie domyślne, stopień 2; stopnia nie widzi pracownik |
| `PositionExperience` | employee, position, level (1–3) | stopień inny niż domyślny na jednym stanowisku; jeden wiersz na parę |
| `pay.PositionRate`, `pay.PersonalRate` | position (+ employee), valid_from, hourly_rate | stawka stanowiska i własna stawka osoby na stanowisku od dnia (sekcja 35) |
| `pay.PaySupplement` | location, name, start_time, end_time, weekdays, kind, value, positions, valid_from, valid_until | dodatek za porę dnia i dni tygodnia (sekcja 35) |

### Dyspozycyjność i prośby

| Model | Pola | Uwagi |
|---|---|---|
| `AvailabilityDay` | employee, date, state (cannot/neutral/prefer; neutral = dzień bez zaznaczenia, potrzebny tylko dla godzin "mogę tylko w tych godzinach"), from_time, to_time (opcjonalne), source (manual/pattern/copy) | unikalne (employee, date); brak wiersza = brak zgłoszenia |
| `AvailabilityPattern` | employee, weekday, state, from/to, repeat_until | "powtarzaj co tydzień do [data]"; rozwijany do `AvailabilityDay` przy zapisie |
| `AvailabilitySubmission` | employee, period, submitted_at | do listy "kto nie zgłosił" |
| `TextRequest` | employee, period lub month, text, status (new/interpreted/needs_manager/rejected/answered/superseded), supersedes, interpretation (JSON), employee_corrected, text_edited_at (kiedy pracownik napisał treść od nowa; data wiadomości w pamięci asystenta to ta chwila, a bez poprawki created_at), manager_priority (lower/normal/higher), manager_rejected, lasting („na stałe”), ends_from (pierwszy dzień okresu lub miesiąca, od którego zakończona prośba na stałe już się nie liczy), ended_by | interpretacja: type, subject_employee, shift_type, avoid, max_hours, dates, weekdays, level, confidence, summary; odpowiedzi informacyjne i zastąpione prośby nie trafiają do generatora |
| `ManagerInstruction` | location, employee, data (JSON jak interpretacja prośby), position (kolejność), source_text, created_by | polecenie kierownika o osobie, przyjęte z planu asystenta (etap 10) |
| `AssistantCommand` | location, text, status (queued/ready/unavailable/failed/applied/dismissed), plan (JSON), created_by, decided_at | polecenie kierownika dla asystenta i sprawdzony plan do akceptacji |

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
| `Assignment` | shift (jeden do jednego), employee (nullable = dziura), pinned, borrowed (z innego lokalu) | dziurę można przypiąć („zostaw pustą na stałe”, od PR #25) |
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

Twarde: każdy slot ma jedną osobę albo `u[s]=1`; brak nakładających się zmian; przypięte przypisania; dni minione zamrożone; zasady "bez wyjątków" (w tym, jeśli kierownik je włączy, "Godziny pracy w ciągu dnia" i "Wolne w tygodniu"). Typu umowy ani wbudowanych limitów Kodeksu pracy nie ma (decyzja Piotra z 13.11.2026).

Cel w dwóch fazach (leksykograficznie): faza 1 minimalizuje `Σ u[s]`, faza 2 przy tej liczbie dziur minimalizuje karę:

```
kara = manager_share × Σ_z  w_z × naruszenie_z            (zasady menedżera)
     + (1 − manager_share) × Σ_p  w_p × naruszenie_p      (prośby pracowników)
     + stability_penalty × liczba zmian względem opublikowanej wersji
```

- `w_z` z miejsca na liście: najwyższa zasada dostaje największą wagę, każda kolejna mniejszą (stały współczynnik `rank_decay`, np. 0,75). Dzięki temu "wszystko najważniejsze" jest niemożliwe z definicji.
- `w_p` z poziomu prośby (bardzo ważne / ważne / mile widziane) i korekty menedżera (ważniejsza / mniej ważna).
- Czas dzielony między fazy (np. 40/60 % limitu). Wynik fazy 1 trafia jako podpowiedź do fazy 2.
- Każdy lokal generujemy osobno (decyzja Piotra z 12.11.2026: lokale są niezależne, każdy z własnymi zasadami i wagami); "Ułóż grafik dla wszystkich" uruchamia osobne generowanie dla każdego lokalu. Przypisania tylko do lokali osoby (główny i dodatkowe, od 19.11.2026); pożyczenie do innego lokalu robi menedżer ręcznie. Opublikowane zmiany tych samych osób w innych lokalach oraz ich zmiany z najnowszych szkiców innych lokali liczą się do odpoczynku, nakładania i godzin.
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
- `GET/POST/PATCH/DELETE /locations/{id}/positions`, `/shift-types`, `/staffing-rules`; obsada jednej daty: `PUT /locations/{id}/staffing-days/{data}` (sekcja 26)
- `GET/PATCH /locations/{id}/employees`, `GET/POST /locations/{id}/invitations`, `POST /invitations/{id}/cancel`

Dyspozycyjność i prośby
- `GET /me/availability?period=` · `PUT /me/availability` (lista dni) · `POST /me/availability/pattern` · `POST /me/availability/copy-previous`
- `POST /me/requests` · `PATCH /me/requests/{id}` (poprawka interpretacji, „Tylko w grudniu” / „Na stałe”) · `GET /me/requests` · `POST /me/requests/{id}/end` („Zakończ” / „Przywróć” prośby na stałe z wcześniejszego miesiąca)
- `GET /periods/{id}/availability` (siatka, kto wysłał, zmiany po terminie) · `GET /periods/{id}/requests` · `PATCH /requests/{id}` (odrzuć / ważniejsza / mniej ważna) · `POST /periods/{id}/requests/{rid}/end` („Zakończ od tego okresu” / „Przywróć”)

Zasady
- `GET /scopes/{type}/{id}/rules` · `PUT /scopes/{type}/{id}/rules` (cała lista z kolejnością) · `POST /scopes/{type}/{id}/rules/preview` (skutek zmiany na ostatnim okresie)

Grafik
- `GET/POST /locations/{id}/periods` · `POST /periods/generate` (jeden lub kilka okresów; osobne `GenerationRun` dla każdego lokalu)
- `GET /generation-runs/{id}` · `GET /versions/{id}` (zmiany, przypisania, ocena, zasady, niespełnione prośby, historia wersji)
- `POST /versions/{id}/check` (proponowana zmiana; odpowiedź: naruszenia + nowa ocena + `can_force`) · `GET /versions/{id}/shifts/{shift_id}/drops` (wynik upuszczenia osoby z tej zmiany na każdą inną zmianę, liczony raz na początku przeciągania) · `PATCH /versions/{id}/assignments` (wpisanie, zamiana, zostawienie bez obsady; `force` zapisuje mimo twardej reguły) · `GET /versions/{id}/employees/{employee_id}/fit` (dyspozycje osoby na zmianach, do podświetlania) · `POST /versions/{id}/shifts/{shift_id}/pin`
- `POST /versions/{id}/draft` (poprawka opublikowanego grafiku) · `DELETE /versions/{id}` (usunięcie szkicu, sekcja 33) · `POST /versions/{id}/publish` · `GET /versions/{id}/shifts/{shift_id}/explain`
- `GET /me/schedule` (tylko opublikowany grafik na najbliższy okres, suma godzin i wypłata brutto w miesiącu, współpracownicy na zmianie)

Oddawanie zmian i powiadomienia
- `POST /me/shifts/{assignment_id}/offer` · `POST /offers/{id}/cancel` · `GET /me/offers?company_id=` · `POST /offers/{id}/claim` · `POST /claims/{id}/withdraw`
- `GET /manager/offers?company_id=` · `POST /claims/{id}/approve` · `POST /claims/{id}/reject`
- `GET /me/notifications?company_id=` · `POST /me/notifications/read`

Raporty
- `GET /reports/hours?company_id=&month=` · `GET /reports/hours.csv?company_id=&month=` (godziny i wypłaty brutto, sekcja 35)

Admin Django: kody subskrypcji (generowanie partii, podgląd użyć), firmy, profile wag.

## 5. Ekrany

Pracownik (telefon)
1. Logowanie: numer telefonu → kod (duże pola, automatyczne przejście, "wyślij ponownie" z odliczaniem).
2. Zaproszenie: nazwa firmy i lokalu, Akceptuj / Odrzuć.
3. Mój grafik: lista najbliższych zmian (data, lokal, godziny, stanowisko, kto ze mną), suma godzin i wypłata brutto, "Oddaj zmianę", sekcja "Zmiany do wzięcia" z przyciskiem "Biorę".
4. Kiedy mogę: kalendarz okresu z czterema stanami (kolor + ikona + wzór, podpis na przyciskach pędzla), wybór stanu "pędzlem" na dole, potem stuknięcie lub przeciągnięcie po dniach, "Powtarzaj co tydzień do…", "Skopiuj z poprzedniego miesiąca", termin zgłoszenia; na dole "Coś jeszcze?" na prośbę tekstem i pokazanie, jak system ją zrozumiał.

Menedżer (komputer)
1. Rejestracja firmy i kod dostępu (także później w Ustawieniach → Subskrypcja).
2. Widok zbiorczy grupy (ekran startowy): lokale w wierszach, stan okresu każdego lokalu (zbieranie dyspozycji / szkic / opublikowany), kto nie zgłosił dyspozycji, przycisk "Ułóż grafik dla wszystkich" (osobne generowanie dla każdego lokalu), przycisk "Poproś o dyspozycje" (powiadomienie do pracowników z okresem i terminem).
3. Ustawienia lokalu: stanowiska, zmiany i godziny, obsada (tabela dzień tygodnia × zmiana × stanowisko) i kalendarz obsady w wybrane dni (sekcja 26), okres i termin dyspozycji.
4. Pracownicy: lista, zaproszenia po numerze, stanowiska, maksimum i cel godzin.
5. Dyspozycje: siatka pracownicy × dni, lista próśb z interpretacją i akcjami, lista osób bez zgłoszenia.
6. Zasady: jedna lista do przeciągania, przełącznik włącz/wyłącz, "bez wyjątków", parametry, podgląd skutku przed zapisaniem.
7. Grafik: siatka dni × zmiany, trzy wartości oceny, dziury wyraźnie oznaczone, przeciąganie i przypinanie z walidacją na żywo, wyjaśnienia po kliknięciu, publikacja i historia wersji.
8. Oddane zmiany: lista do zatwierdzenia.
9. Godziny: podsumowanie miesiąca z podziałem na lokale i wypłatami brutto, eksport CSV.

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
2. Brak zgłoszenia dyspozycji = dzień bez zaznaczenia ("mogę"), ale osoba jest na liście "nie zgłosił" u menedżera.
3. Generator przypisuje ludzi tylko do ich lokali (główny i dodatkowe, sekcja 27); praca w innym lokalu tylko ręcznie albo przez wzięcie oddanej zmiany.
4. Zmiany typu "dowolne godziny" generator traktuje jak sloty z godzinami ustawionymi w obsadzie lub wyjątku na dany dzień; menedżer może też dodać zmianę z dowolnymi godzinami ręcznie.
5. Tydzień zaczyna się w poniedziałek, strefa czasowa Europe/Warsaw, godziny zmian liczone w czasie lokalnym z uwzględnieniem zmiany czasu.
6. Menedżer też może mieć profil pracownika (np. kierownik, który sam stoi na zmianach).
7. Rejestracja firmy możliwa bez kodu; firma dostaje wtedy 30 dni okresu próbnego (decyzja Piotra z 12.11.2026, 13.11.2026 wydłużone z 14 dni; zob. sekcja 14), potem jest tylko do odczytu, dopóki nie wpisze kodu.
8. Odświeżanie wyniku generowania przez odpytywanie co 1–2 s, bez websocketów.
9. CI na GitHub Actions (ruff, pytest, eslint, typecheck, build) to część stosu narzędzi, nie aplikacji; dodam w etapie 1, jeśli się zgadzasz.
10. Row Level Security w Postgresie odłożone; izolacja w warstwie aplikacji z testami.

## 8. Uwagi na kolejne etapy (z przeglądu etapu 2)

- Usuwanie a historia (od etapu 2 pilnuje tego baza, `on_delete=RESTRICT`): nie da się usunąć pojedynczo lokalu z okresami grafiku, okresu z wersjami, stanowiska użytego w zmianach ani pracownika z przypisaniami. Usunięcie całej firmy (tylko superadmin, np. firma testowa) nadal usuwa wszystko. Etap 7: pracownika wyłącza się przez `is_active = false`, a lokal archiwizuje (nowe pole przy ekranach). Od 18.11.2026 (sekcja 25) da się też usuwać: tam, gdzie baza blokuje, osoba i stanowisko są ukrywane (`removed_at`), lokal usuwa się tylko bez pracowników i okresów, a okres tylko przed pierwszą publikacją (razem ze szkicami).
- Etap 7 (zrobione): lista zasad lokalu pokazuje, które zasady są dziedziczone z grupy, a które zmienione lub wyłączone w lokalu.
- Etap 3: zmiana numeru telefonu pracownika robi superadmin w panelu (historia zostaje, bo jest przypięta do konta, nie do numeru); zaproszenia oczekujące na stary numer trzeba wysłać ponownie. Numery spoza Polski: poza prototypem.
- Etap 6/7 (z przeglądu etapu 3): na ekranie zaproszeń menedżer widzi podpowiedź "Powiedz tej osobie, żeby zalogowała się tym numerem" (SMS z zaproszeniem nie idzie) oraz informację, że zaproszona osoba pracuje już w innym lokalu firmy i zachowa tamten lokal domowy. Komunikat trybu tylko do odczytu rozróżnia firmę bez kodu od firmy po wygaśnięciu. W trybie tylko do odczytu pracownik nadal widzi swój opublikowany grafik.
- Etap 7/8 (z przeglądu etapu 4): ~~przy wyniku dla umowy o pracę uwaga o uproszczonym Kodeksie pracy~~ (nieaktualne: typ umowy usunięty 13.11.2026); przy zasadzie "Cel godzin" z "bez wyjątków" napis "do 10 % odchylenia"; zasady bez niczego do oceny pokazane jako "nic do oceny", a prośby "inne" jako "do oceny przez kierownika" obok procentów; zmiany pożyczonych osób widoczne w grafiku lokalu, który je przyjmuje. Do sprawdzenia z pilotem: czy równy podział weekendów ma też wyłapywać osoby bez żadnej zmiany (dziś pomija je, łapie je tylko cel godzin).
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
2. Osoba, która już pracuje w innym lokalu tej samej firmy i przyjmie zaproszenie pracownika do kolejnego, zachowuje dotychczasowy lokal domowy, a nowy lokal dostaje jako dodatkowy (od 19.11.2026, sekcja 27).
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
2. (Nieaktualne od 13.11.2026: typ umowy usunięty, te same sprawdzenia są teraz zasadami z katalogu, patrz "Bez typu umowy i Kodeksu pracy".) Umowa o pracę, uproszczenia zgodne ze spec (doba pracownicza i okres rozliczeniowy później): 11 h odpoczynku między końcem zmiany a początkiem następnej (dokładnie 11 h wystarcza, 10 h 59 min nie); najwyżej 8 h łącznie w zmianach zaczynających się danego dnia kalendarzowego; 35 h nieprzerwanego wolnego w każdym tygodniu kalendarzowym (pon. 00:00 – pon. 00:00 czasu lokalnego), sprawdzane w tygodniach, w których osoba ma zmianę z tego grafiku.
3. Zmiany stykające się (06–14 i 14–22) nie nachodzą na siebie; to poprawny grafik, chyba że kierownik włączy zasady odpoczynku lub godzin w ciągu dnia.
4. Zmiany spoza okresu (poprzedni okres, inny lokal) przekazuje warstwa Django jako `ExternalShift`; liczą się do nakładania, odpoczynku, 8 h na dobę i dni z rzędu, nie do godzin miesięcznych.
5. Dyspozycyjność: wpis bez godzin dotyczy każdej zmiany zaczynającej się tego dnia. Wpis z godzinami: "nie mogę" dotyczy zmian nachodzących na ten zakres (styk się nie liczy), "chętnie" i dzień bez zaznaczenia z godzinami tylko zmian mieszczących się w zakresie.
6. Prośby z kalendarza (od 13.11.2026 bez "wolę nie", które przeszło do próśb tekstem jako wolne_dni): dni "chętnie" jednej osoby to jedna pozycja o wadze "mile widziane", liczona jako udział dni pracy przypadających na dni "chętnie" (spośród tylu dni, ile się da). Osoba bez zmian nie łamie "chętnie".
7. Prośby tekstem: unikaj osoby / preferuj osobę = udział zmian prośbodawcy, na których ta druga osoba pracuje w tym samym lokalu w tym samym czasie; typ zmiany = udział zmian innego typu (albo tego typu przy "nie chcę"); limit godzin = nadwyżka / limit; "inne" nie są oceniane. Waga = waga poziomu × korekta menedżera (ważniejsza ×2, mniej ważna ×0,5). Odrzucone prośby nie trafiają do `Problem`.
8. Zasady liczone per lokal: zasady dotyczące osoby (odpoczynek, dni z rzędu, godziny, pora w tygodniu, zmiany w tygodniu) dla osób z tym lokalem domowym, zasady dotyczące zmian (zamknięcia, pora stanowiska) dla slotów tego lokalu. Stopień naruszenia zasady = udział miejsc, w których jest złamana (np. par kolejnych zmian, dni pracy, tygodni osoby), albo dla godzin średnie względne odchylenie.
9. Równy podział weekendów i zamknięć: osobno dla każdego stanowiska, porównujemy osoby z tym stanowiskiem, które mają w okresie choć jedną zmianę; różnica 1 jest w porządku. Zasada "bez wyjątków" = różnica najwyżej 1.
10. Cel i maksimum godzin miesięcznych są proporcjonalne do części miesiąca objętej okresem (tydzień listopada = 7/30 celu). Cel godzin "bez wyjątków" dopuszcza odchylenie 10 %.
11. Ocena: zasady "bez wyjątków" nie wchodzą do procentów (to ograniczenia), tak samo zasady bez niczego do zmierzenia (np. równe zamknięcia, gdy nie ma zmian zamykających); `Scores` podaje ich liczbę (`unmeasured_rules`) oraz liczbę próśb "inne" zostawionych menedżerowi (`unscored_requests`), żeby 100 % nie wyglądało na "wszystko sprawdzone". Waga zasady wynika z miejsca wśród zasad miękkich lokalu: 1, `rank_decay`, `rank_decay²`… Brak pozycji w grupie = 100 %.
12. `stability_penalty` w profilu wag oznacza punkty skali 0–100 za każdą zmianę opublikowanego przypisania (domyślnie 5).
13. Pożyczenie osoby do innego lokalu nie jest błędem walidatora (robi je menedżer ręcznie); ograniczenie do lokalu domowego dotyczy tylko generatora.

## 11. Etap 5: generator i przyjęte założenia

- `engine/solver.py`: `solve(problem, time_limit_s, workers, seed, weights=None, diversity_from=())` buduje model CP-SAT z tego samego `Problem` co walidator. Faza 1 minimalizuje dziury (40 % limitu czasu; na danych demo dowód optimum w ok. 1–2 s), faza 2 przy tej liczbie dziur minimalizuje karę z `engine.scoring.penalty`, z podpowiedzią z fazy 1. Każda zasada z katalogu ma metodę `_rule_<kod>`: dla "bez wyjątków" ograniczenie, dla zwykłej kara.
- Kara w modelu odwzorowuje ocenę walidatora: dokładnie dla próśb tekstem (poza mianownikiem udziału), celu i maksimum godzin, dni z rzędu, osoby odpowiedzialnej na zamknięciu, równego podziału (dzielenie w modelu) i stabilności. Zasady liczone jako udział w zmiennej liczbie miejsc (odpoczynek, ta sama pora w tygodniu, zmiany w tygodniu, stała pora stanowiska) i "chętnie" dzielą przez oszacowanie tej liczby. Menedżer zawsze widzi ocenę z walidatora, nie wartość z modelu.
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
8. Limitu generowań nie ma (usunięty 22.11.2026, sekcja 39). Zlecenia jednej firmy przechodzą po kolei (blokada na wierszu firmy), a drugie zlecenie dla okresu, który już się układa, dostaje 409.
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
4. "Cofnij" zapisuje poprzedni stan dni; dzień bez wcześniejszego zaznaczenia wraca do stanu bez zaznaczenia (wiersz "neutral" zostaje, co dla generatora znaczy to samo co brak wiersza).
5. "Mój grafik" pokazuje opublikowane zmiany od dziś na 62 dni naprzód; suma godzin dla bieżącego miesiąca i każdego miesiąca z listy liczy wszystkie opublikowane zmiany tego miesiąca (także te, które minęły). "Z Tobą" to osoby z opublikowanego grafiku tego samego lokalu, których zmiana nakłada się na moją; na ekranie trzy imiona i liczba pozostałych.
6. Godziny dnia (prośba Piotra): zmienia się znaczenie godzin w silniku (`engine.problem.Availability`): "chętnie" i dzień bez zaznaczenia z godzinami = tylko w tych godzinach, poza nimi "nie mogę"; koniec przed początkiem = do rana. Ograniczenie w bazie zmienione z "początek przed końcem" na "początek różny od końca".
7. Kierownik bez profilu pracownika, który wejdzie na ekrany pracownika, widzi komunikat, że nie jest pracownikiem; jego ekrany powstają w etapie 7.


## 13. Etap 7: ekrany menedżera

- Zasada produktowa (Piotr, 12.11.2026, spec.md punkt 6 menedżera): grafik powstaje tylko na świadome polecenie kierownika, po terminie dyspozycji albo przy komplecie. W kodzie nic nie układa grafiku samo; zadania okresowe workera to tylko sprzątanie kodów logowania i oznaczanie zawieszonych generowań jako nieudane.
- Ekrany (`frontend/src/features/manager/`, trasy `/kierownik/...`): "Lokale" (start kierownika: każdy lokal z okresem, terminem, paskiem "wpisali X z Y", listą osób bez dyspozycji, liczbą dni zmienionych po terminie, przyciskiem "Poproś o dyspozycje" / "Przypomnij (N)" i napisem "Można układać grafik", gdy termin minął albo wszyscy wpisali; archiwum lokali), a w lokalu karty "Dyspozycje" (okres i termin, siatka pracownicy × dni z godzinami i znakiem zegara przy zmianach po terminie, prośby tekstem z decyzją kierownika), "Pracownicy" (stanowiska, cel i maksimum godzin, wyłączenie z grafiku, zaproszenia), "Ustawienia lokalu" (dane lokalu, stanowiska, zmiany i godziny, tabela obsady, wyjątki na daty, archiwizacja) i "Zasady" (jedna lista do przeciągania albo strzałkami, przełącznik, "bez wyjątków", parametry, "z grupy" / "zmienione w tym lokalu", podgląd skutku przed zapisem). Zasady grupy: `/kierownik/grupa/{id}/zasady`.
- Nowe pola: `Location.archived_at`, `SchedulePeriod.availability_deadline` (dzień układania = ostatni dzień dyspozycji; puste = `availability_deadline_days` lokalu) i `SchedulePeriod.availability_requested_at`.
- Nowe endpointy: `GET /manager/overview?company_id=`, `POST /groups`, `POST /locations`, `GET/PATCH /locations/{id}` (także `archived`), `GET /locations/{id}/setup`, `POST /locations/{id}/positions`, `PATCH/DELETE /positions/{id}`, `POST /locations/{id}/shift-types`, `PATCH/DELETE /shift-types/{id}`, `PUT /locations/{id}/staffing` (cała tabela tygodnia), `POST /locations/{id}/staffing-exceptions`, `DELETE /staffing-exceptions/{id}`, `GET /locations/{id}/employees`, `PATCH /employees/{id}`, `PATCH /periods/{id}` (termin), `POST /periods/{id}/ask-availability`, `GET /periods/{id}/availability`, `GET /periods/{id}/requests`, `PATCH /requests/{id}`, `GET/PUT /scopes/{location|group}/{id}/rules`, `POST /scopes/{location|group}/{id}/rules/preview`.

Założenia:
1. "Zmienione po terminie" = dzień dyspozycji zapisany (`AvailabilityDay.updated_at`) od północy dnia po terminie, w strefie lokalu. Pracownik może zmieniać do ułożenia grafiku (decyzja Piotra).
2. "Poproś o dyspozycje" zapisuje powiadomienie w aplikacji (`Notification`, rodzaj `availability_requested`) dla każdego aktywnego pracownika lokalu; "Przypomnij" tylko dla tych bez "Gotowe". Pokazanie powiadomień pracownikowi to etap 9. Działa tylko w okresie "zbieranie dyspozycji".
3. Zasady lokalu: ekran wysyła całą listę po kolei. Zasada ustawiona dokładnie jak w grupie i na tym samym miejscu dalej idzie za grupą (bez wiersza lokalu); inaczej lokal zapisuje własne ustawienie (także gdy zmieniło się tylko miejsce na liście, bo kolejność całej listy jest jedna). Etykieta „zmienione w tym lokalu” obejmuje także zmianę kolejności. „Przywróć jak w grupie” odtwarza zarówno wartości, jak i miejsce zasady. Po zapisie lokal znów dziedziczy tę zasadę. Zasady z parametrem stanowiska lub zmiany ("Stała pora dla stanowiska", "Ktoś odpowiedzialny na zamknięciu") ustawia się tylko w lokalu. Nowy lokal bez grupy startuje z włączonymi zasadami dobrej praktyki.
4. Podgląd skutku zasad nie układa grafiku od nowa (solver działa tylko w workerze): sprawdza walidatorem ostatni grafik lokalu (opublikowany, a bez niego najnowszy szkic) z obecnymi i z nowymi zasadami i mówi, ile razy każda zmieniona zasada byłaby złamana, oraz jak zmieni się ocena "zasady kierownika". Bez ułożonego grafiku podgląd mówi, że nie ma na czym sprawdzić. Pełne "co by było" (np. ile próśb przestałoby być spełnionych po ponownym ułożeniu) może być zadaniem workera w etapie 8.
5. Formularz obsady i API przechowują liczbę osób, wymaganą liczbę doświadczonych i godziny zmiany z dowolnymi godzinami osobno dla każdego dnia tygodnia, stanowiska i typu zmiany. „Cały tydzień jak pon.” kopiuje wszystkie te wartości. Gdy dzień wymaga obsady, a godziny nie wynikają ani z komórki, ani z typu zmiany, formularz wskazuje brak. Godziny można uzupełnić przed układaniem grafiku. Usunięcie stanowiska użytego w ułożonym grafiku jest odrzucane (409), można zmienić nazwę; usunięcie zmiany zostawia ułożone grafiki (godziny są w nich skopiowane).
6. Lokal archiwizuje tylko właściciel; archiwalny lokal znika z listy i z generowania (409), historia zostaje. Grupę lokali zakłada i zmienia tylko właściciel.
7. Pracownika "wyłącza z grafiku" kierownik jego lokalu (`is_active = false`); jego dawne zmiany zostają.

Na etap 8 (dopisane tutaj, nie zrobione w etapie 7): przycisk "Ułóż grafik" przy lokalu, aktywny jako świadoma akcja, z podpowiedzią, gdy termin minął albo wszyscy wpisali (i ostrzeżeniem, ilu osób brakuje); "Ułóż dla wszystkich". Ekran rejestracji firmy i wpisania kodu dostępu (API jest od etapu 3) też nie powstał w etapie 7; do zrobienia razem z etapem 8 albo osobno.

Po przeglądzie Prelinta (PR #9): komunikat po "Poproś o dyspozycje" mówi, że pracownicy zobaczą powiadomienie w jednej z następnych wersji i że na razie trzeba im powiedzieć osobiście; podgląd zasad mówi wprost, że to sprawdzenie ostatniego grafiku, a nie prognoza; ekran zasad lokalu tłumaczy, kiedy zasada przestaje iść za grupą; licznik to "Wysłali dyspozycje" (przycisk "Gotowe"), nie zaznaczone dni. Do sprawdzenia w pilocie: czy kierownik chce móc pominąć zmiany po terminie, czy podgląd na ostatnim grafiku wystarcza, i czy ktoś poza właścicielem musi zakładać lokale i grupy.

## 14. Etap 8: układanie z ekranu, edycja, publikacja, godziny

- Decyzja Piotra (12.11.2026): firma założona bez kodu dostaje okres próbny (`Subscription.source = "trial"`, `TRIAL_DAYS` w ustawieniach, domyślnie 30). Najpierw 14 dni; 13.11.2026 Piotr zgodził się na 30 po uwadze Prelinta, że 14 dni nie mieści pełnego miesięcznego cyklu. Po nim tryb tylko do odczytu jak po wygaśnięciu kodu; baner i ekran "Dostęp" mówią, ile dni zostało.
- Ekrany: "Załóż firmę" (`/rejestracja`: numer, kod SMS, nazwa firmy, imię i nazwisko, opcjonalny kod; link z ekranu logowania), "Dostęp" (`/kierownik/dostep`: stan i wpisanie kodu), baner dostępu w panelu kierownika, "Godziny" (`/kierownik/godziny`: miesiąc, tabela osób z podziałem na lokale, CSV) i karta "Grafik" w lokalu (`/kierownik/lokal/{id}/grafik`). Na "Lokale" przycisk "Ułóż grafik" przy każdym lokalu i "Ułóż dla wszystkich" (każdy lokal osobno), z arkuszem, który ostrzega przed terminem, mówi, ilu osób brakuje i ile nieprzypiętych ręcznych poprawek zniknie; postęp odpytywany co 1,5 s.
- Karta "Grafik": trzy wartości oceny, twarde problemy, siatka dni × zmiany (przypięte, ręczne, pożyczone, bez obsady; znacznik "woli nie" usunięty 13.11.2026, zob. sekcja 15), przeciąganie osoby na inną zmianę z wynikiem sprawdzenia na żywo w trakcie przeciągania (prośba Piotra z 18.11.2026: bez napisu "Sprawdzam…"; gdy kierownik chwyci kafelek, jedno zapytanie liczy wynik dla wszystkich zmian, więc po najechaniu na zmianę wynik jest od razu; zanim ta odpowiedź przyjdzie, zmiana pod kursorem jest sprawdzana osobno, bez opóźnienia), arkusz zmiany z wyjaśnieniem (kto może, ile to kosztuje, kto nie może i dlaczego) i akcjami "Wpisz", "Zostaw bez obsady", "Przypnij", godziny osób, zasady z procentem, niespełnione prośby, wersje, "Opublikuj" i "Popraw grafik".
- Nowe pole `Assignment.manual` (ręczna zmiana). Nowy moduł `engine/explain.py` (bez Django): dla każdej osoby ze stanowiskiem sprawdza walidatorem grafik z tą osobą na zmianie, więc wyjaśnienie zgadza się z walidatorem. `apps/scheduling/editing.py`: sprawdzanie i zapis ręcznych zmian, przypinanie, poprawka opublikowanego grafiku, publikacja. Raport godzin: `apps/reports`.

Założenia:
1. Ręcznie można zmieniać tylko najnowszy szkic okresu (wyjątki: zatwierdzona oddana zmiana z etapu 9, zob. sekcja 18 punkt 4, oraz własne zmiany kierownika w "Oddane zmiany": inna osoba na zmianie i zamiana dwóch osób, zob. sekcja 24; tam kierownik może pominąć zastrzeżenia walidatora i poprawić też dni, które minęły). Opublikowany grafik poprawia się przez "Popraw grafik" (kopia jako nowy szkic), a starsze szkice dostają status "zastąpiony" przy nowym szkicu lub publikacji. Dni, które minęły, też można poprawić w szkicu (niżej); tylko miejsc w obsadzie na takie dni nie da się zmienić (409, sekcja 26).
2. Ręczna zmiana, która dodaje naruszenie twardej reguły, jest odrzucana (409 z powodem), poza wymogiem doświadczonych, który kierownik może złamać (ostrzeżenie zamiast odmowy; sekcja 26, punkt 7); miękkie skutki (np. ponad cel godzin) są pokazane jako ostrzeżenie, ale dozwolone. Zmieniona ręcznie zmiana traci przypięcie; "Przypnij" trzeba kliknąć osobno. Zmianę bez obsady można przypiąć jako pustą (od PR #25, patrz sekcja 22).
3. W edytorze można wpisać tylko osoby z lokalu (z danym stanowiskiem); pożyczanie z innych lokali zostaje dla oddawania zmian (etap 9).
4. Publikacja jest możliwa z dziurami (kierownik dostaje ostrzeżenie), ale nie z naruszeniem twardej reguły; wyjątek: brak doświadczonych po ręcznej zmianie kierownika (sekcja 26, punkt 7). Historia przypisań (`AssignmentEvent`) jest zapisywana przy publikacji, dla każdej zmienionej względem poprzedniej publikacji zmiany, z powodem "ręcznie" albo "ułożone". Publikacja zapisuje powiadomienie `schedule_published` dla pracowników lokalu (pokazanie to etap 9).
5. Okres próbny dostaje tylko pierwsza firma danej osoby; kolejne firmy bez kodu są od razu tylko do odczytu.
6. Wyjaśnienie zmiany liczy szybkie sprawdzenie walidatorem dla każdej osoby (ok. 5 ms na osobę). Głębsza analiza ("kto by mógł, gdyby przestawić inne zmiany") wymaga solvera w workerze i zostaje na później.
7. Raport godzin liczy tylko opublikowane zmiany w lokalach, którymi zarządza kierownik, w podanym miesiącu kalendarzowym (zmiana należy do dnia, w którym się zaczyna). CSV: średniki, przecinek dziesiętny, BOM, żeby Excel otworzył polskie znaki.


Swobodna edycja (decyzje Piotra z 18.11.2026; zmieniają punkty 2 i 4 wyżej):
- Wymuszenie: `PATCH /versions/{id}/assignments` przyjmuje `force: true`. Zmiana, która dodaje twarde naruszenie, bez `force` nadal dostaje 409, a z `force` jest zapisywana z `Assignment.forced = true` i przypięta. `Problem.forced` (slot -> osoba) mówi walidatorowi, żeby naruszenia dotyczące tej osoby na tym slocie (`cannot`, `one_shift`, `experience`, zasada "bez wyjątków") trafiły do `ValidationReport.waived` zamiast `hard`: widać je przy zmianie jako "wpisane mimo przeszkód", ale nie blokują publikacji ani kolejnych poprawek. Stanowisko, przypięcia i dwie zmiany w tym samym czasie (`overlap`) zostają twarde; tę ostatnią kierownik rozwiązuje pytaniem i zdjęciem osoby z tamtej zmiany (sekcja 27). Wyjaśnienie zmiany zwraca przy każdej zablokowanej osobie `can_force`. Wymuszenie kończy się, gdy slot dostaje inną osobę. `POST /versions/{id}/check` zwraca `can_force`.
- Solver nie modeluje wymuszonych przypisań: przypięte albo z minionego dnia wyjmuje z problemu jako zmiany, które osoba już ma (bez nakładania, z odpoczynkiem), i dokleja do wyniku. Dzięki temu "Ułóż od nowa" działa także wtedy, gdy wymuszenie łamie twardą regułę.
- Dni, które minęły, można poprawiać w szkicu. Taka poprawka jest przypinana sama, a przypięcie na minionym dniu wygrywa z zamrożeniem (walidator nie zgłasza wtedy `frozen`), więc ponowne układanie zostawia poprawkę także przed publikacją. Godziny liczą się z opublikowanej wersji, więc poprawkę trzeba opublikować.
- Podświetlanie: `GET /versions/{id}/employees/{employee_id}/fit` zwraca dla każdej zmiany ze stanowiskiem osoby, której ta osoba nie ma: `prefer` / `can` / `cannot` z powodem (tylko kalendarz i nakładanie się zmian, bez pełnej walidacji, żeby odpowiedź była natychmiast). Siatka koloruje kafelki dla osoby wybranej z listy albo przeciąganej (`.avail-prefer`, `.avail-neutral`, `.fit-cannot` + `StateIcon`).

Po przeglądzie Prelinta (PR #10): nad siatką jest pasek "Ręczne poprawki bez przypięcia: N" z przyciskiem "Przypnij poprawki", bo ponowne układanie je usuwa; arkusz publikacji mówi, że powiadomień w aplikacji jeszcze nie ma (trzeba powiedzieć pracownikom), a przy poprawce opublikowanego grafiku wymienia osoby, których zmiany się zmieniają (`VersionOut.changed_people`); ekran "Godziny" mówi, że to plan z opublikowanych grafików w lokalach kierownika, a nie ewidencja czasu pracy, i oznacza osobę, która w tym miesiącu pracuje też w lokalach, których kierownik nie prowadzi (suma niepełna; w CSV kolumna "Uwagi"). Ręczna zmiana osoby w edytorze zawsze zdejmuje przypięcie (wyjątek od etapu 9: zatwierdzona oddana zmiana jest przypięta, bo to uzgodnienie trzech osób, a nie poprawka kierownika do przemyślenia). Link "Załóż firmę" zostaje w pustym stanie zaproszeń, bo to jedyna droga do rejestracji dla zalogowanej osoby bez firmy (np. kierownika, który najpierw się zalogował). Do sprawdzenia w pilocie: czy kierownik oczekuje, że ręczne poprawki zostają domyślnie, i czy potrzebuje obejścia „nie mogę” po rozmowie z pracownikiem.

## 15. Zmiana z 13.11.2026: w kalendarzu tylko "nie mogę" i "chętnie"

Decyzja Piotra po przeglądzie zrzutów: "wolę nie" i "obojętnie" znikają z kalendarza; takie życzenia pracownik pisze jako prośbę tekstem, a LLM (etap 10) zamienia je na nowy typ `wolne_dni`.

1. Stan `neutral` zostaje w bazie i silniku jako "dzień bez zaznaczenia" ("mogę"): niesie godziny "mogę tylko w tych godzinach" i zostaje po wyczyszczeniu dnia. Dla generatora znaczy to samo co brak wiersza.
2. Na pędzlu są trzy przyciski: "Nie mogę", "Wyczyść" (gumka, zdejmuje stan i godziny) i "Chętnie". W arkuszu dnia i w "Więcej opcji" ten stan nazywa się "Mogę".
3. Migracja `availability.0003` zamienia istniejące dni i wzorce "wolę nie" na dni bez zaznaczenia i usuwa ich godziny (godziny przy "wolę nie" znaczyły "nie w tych godzinach", a przy dniu bez zaznaczenia znaczyłyby "tylko w tych godzinach").
4. Typ prośby `wolne_dni` (`RequestType.DAYS_OFF`): stopień złamania = część podanych dni, w które osoba pracuje; bez dat prośba trafia do kierownika jako "inne". W solverze kara za każdy z tych dni, w który osoba ma zmianę.
5. Do etapu 10 prośby tekstem nie mają interpretacji, więc życzenia typu "wolę nie" widzi tylko kierownik, a generator ich nie liczy.
6. Siatka kierownika: dzień bez zaznaczenia to pusta kratka z pełną ramką; przerywana ramka zostaje dla osób, które nic nie wysłały.
7. Po połączeniu z etapem 8: siatka grafiku, wyjaśnienie zmiany i lista niespełnionych próśb nie znają już "wolę nie" (bez znacznika "woli nie" i bez pozycji `prefer_not`); w wyjaśnieniu dzień bez zaznaczenia to "bez zaznaczenia".

## 15a. Poprawki po testach Piotra (13.11.2026): prostsze "Kiedy mogę"

Piotr z kolegą przetestowali wdrożoną aplikację. Zmiany w tej części (nadpisują punkty 2 i 6 sekcji 15 oraz "Cofnij" i "Więcej opcji" z sekcji 12):

1. Pędzel ma trzy stany: "Nie mogę", "Mogę", "Chętnie". Nie ma gumki "Wyczyść"; "Mogę" to zwykły stan (`neutral`), jasnozielony z cienkim ptaszkiem, "Chętnie" to pełniejsza zieleń z podwójnym ptaszkiem. Dzień bez wiersza w bazie wygląda i czyta się tak samo jak "Mogę".
2. Znikają przyciski "Cofnij" i "Więcej opcji" (powtarzanie co tydzień, kopiowanie z poprzedniego miesiąca). Endpointy `repeat_my_availability` i `copy_previous_availability` zostają w API bez ekranu (dane demo ich używają); do usunięcia, jeśli nie wrócą.
3. Siatka kierownika: legenda ma trzy stany, dzień bez wpisu to "Mogę"; kto nie wysłał dyspozycji, ma jak dotąd znacznik "Nie wysłano" przy nazwisku.
4. Zakładki pracownika: mniejszy podpis i kolumny nie węższe niż tekst, więc "Powiadomienia" mieszczą się na ekranie 320 px.
5. Kierownik czyta powiadomienia w panelu kierownika (`/kierownik/powiadomienia`), a nie na ekranach pracownika.

6. Anulowanie układania grafiku: `POST /generation-runs/{id}/cancel` (kierownik lokalu, firma z dostępem) ustawia `GenerationRun.status = cancelled` i oddaje ułożenie do limitu. Zadanie w kolejce po prostu nic nie zrobi; liczący solver pyta o anulowanie mniej więcej co sekundę (`engine.solver.solve(should_stop=...)`, wątek pomocniczy wywołuje `stop_search`) i kończy bez wyniku. Wynik, który dotarł już po anulowaniu, nie jest zapisywany. Ekran: przycisk "Anuluj" obok "Układam grafik…" na liście lokali i w zakładce "Grafik".
7. Pędzel nadal zdejmuje godziny dnia przy zmianie stanu (uwaga Prelinta do PR #20: bez "Cofnij" źle przeciągnięty palec kasuje godziny i trzeba je wpisać jeszcze raz). Zostaje do decyzji Piotra po pilotażu: pędzel zachowujący godziny albo powrót "Cofnij".

8. Kierownik jako pracownik (prośba Piotra z 13.11.2026: w kawiarniach kierownik często sam staje na zmianie i każdego zastąpi): w zakładce "Pracownicy" przycisk "Dodaj mnie jako pracownika" (`POST /locations/{id}/employees/me`) zakłada kierownikowi profil pracownika w tym lokalu ze wszystkimi stanowiskami lokalu, bez zaproszenia na własny numer. Profil wyłączony wcześniej włącza się z powrotem. Jedna osoba ma jeden lokal główny; kierownik, który jest już pracownikiem innego lokalu, dodaje się tym przyciskiem jako lokal dodatkowy (od 19.11.2026).

9. "Kiedy mogę" jest zawsze otwarte (prośba Piotra z 13.11.2026: pracownicy mają móc zaznaczać dostępność na przyszłość, także zanim kierownik o nią poprosi; wcześniej ekran był pusty do czasu prośby). Ekran pokazuje kalendarz miesiącami (bieżący i trzy kolejne, strzałki), a nie jeden okres. Nowe endpointy: `GET /me/calendar?start&end` (dni, lista dni zamkniętych, najbliższy okres zbierający dyspozycje, data wysłania) i `PUT /me/calendar` (zapis bez `period_id`). Zamknięte są tylko dni, które minęły, i dni okresu z ułożonym grafikiem (szkic albo opublikowany); zapis najwyżej rok naprzód. `AvailabilityDay` było od początku kluczowane datą, więc kierownik widzi wcześniejsze zaznaczenia w siatce okresu bez zmian po swojej stronie. Gdy kierownik poprosi o dyspozycje, ekran otwiera się na miesiącu tego okresu i pokazuje termin oraz "Gotowe, wysyłam kierownikowi"; prośby tekstem nadal pisze się do konkretnego okresu, więc pojawiają się dopiero po prośbie kierownika. Stare `PUT /me/availability` zostaje w API (nieużywane przez ekran).

10. Redakcja tekstów (prośba Piotra z 13-14.11.2026: "bardziej po polsku", "ma być prosto i wiadomo"). Teksty ekranów przepisane według zasad prostego języka (wzorce: gov.pl "Prosty język", standard UM Warszawa, bankowość, polskie aplikacje grafikowe):
    - najważniejsze na początku, krótkie zdania, jedna myśl w zdaniu, bez średników;
    - zwracamy się na "ty", strona czynna, czasowniki zamiast rzeczowników ("Możesz układać grafik", nie "Można układać grafik");
    - przycisk to polecenie, które mówi, co się stanie: "Wyślij kierownikowi", "Weź zmianę", "Zrezygnuj", "Jednak nie oddaję", "Przyjmij zaproszenie", "Sprawdź i zapisz";
    - błąd mówi, co się stało i co zrobić; pusty ekran mówi, co tu będzie i co zrobić;
    - jedno słowo na jedną rzecz. Zostają: "dyspozycje", "kierownik", "lokal", "obsada", "szkic", "przypięte", zakładka "Kiedy mogę". Znikają: "siatka dyspozycji" (teraz "Kto kiedy może"), "okres grafiku" w tekstach dla ludzi ("daty grafiku"), "generator" ("ułożone automatycznie");
    - bez form zależnych od płci tam, gdzie się da.
    Nowe teksty piszemy według tych samych zasad. Gdy nie ma prośby kierownika, "Kiedy mogę" mówi wprost, że prośbę tekstem pisze się dopiero, gdy kierownik poprosi o dyspozycje (uwaga Prelinta do PR #20).

## 16. Zmiana z 13.11.2026: stopień doświadczenia pracownika

Decyzja Piotra: kierownik na liście pracowników daje każdej osobie etykietę z jednym z trzech stopni doświadczenia, pracownik jej nie widzi, a generator pilnuje, żeby na zmianie nie było wielu niedoświadczonych.

1. `EmployeeProfile.experience`: 1 = początkujący, 2 = samodzielny (domyślny), 3 = doświadczony. Dopóki kierownik nikogo nie oznaczy, wszyscy są samodzielni i zasada nic nie zmienia.
2. Stopień jest tylko w API kierownika (`GET /locations/{id}/employees`, `PATCH /employees/{id}`). Żaden endpoint pracownika go nie zwraca.
3. Nowa zasada katalogu `experience_mix` ("Początkujący z doświadczonymi"), dobra praktyka (włączona w nowych lokalach): na każdej zmianie (dzień × typ zmiany w lokalu) liczba początkujących nie może przekraczać liczby doświadczonych. Samodzielni się nie liczą. Parametr `position` (puste = wszystkie stanowiska razem) zawęża liczenie do jednego stanowiska, np. kelnerów.
4. Stopień złamania = część zmian, na których początkujących jest więcej niż doświadczonych. Solver: kara za każdą taką zmianę (twarda: ograniczenie "początkujących ≤ doświadczonych").
5. Migracja dopisuje zasadę na koniec listy w istniejących lokalach bez grupy i w grupach, które mają już zasady (najmniejsza waga, łatwo przesunąć albo wyłączyć).
6. Dane przykładowe: w każdym lokalu kilka osób początkujących i kilka doświadczonych.
7. Na później (pomysł Piotra): podpowiedź stopnia z liczby przepracowanych godzin.

## 17. Bez typu umowy i Kodeksu pracy (13.11.2026)

Decyzja Piotra po przeglądzie UX: usuwamy typ umowy (zlecenie / umowa o pracę) i wbudowane, zawsze twarde ograniczenia umowy o pracę. Aplikacja w to nie ingeruje; kierownik ustawia wszystko w zasadach.

- `EmployeeProfile.contract` usunięte (migracja `staffing`), znika z API (`EmployeeOut`, `EmployeeIn`), panelu admina, danych demo, ekranu "Pracownicy" i silnika (`Employee.contract`, `Contract`, kody `labor_*`, `check_labor_law`, `_labor_law`).
- Dwie nowe zasady w `engine/rules_catalog.py`, miękkie albo "bez wyjątków" jak każda inna (od 13.11.2026 dobra praktyka, patrz założenie 2):
  - `max_hours_per_day` "Godziny pracy w ciągu dnia", parametr `max_hours` (8): łączny czas zmian zaczynających się danego dnia kalendarzowego (także zmian spoza grafiku) nie przekracza limitu. Stopień złamania = dni ponad limit / dni pracy.
  - `min_weekly_rest` "Wolne w tygodniu", parametr `rest_hours` (35): w każdym tygodniu (pon. 00:00 – pon. 00:00 czasu lokalnego), w którym osoba ma zmianę z grafiku, ma tyle godzin wolnego bez przerwy. Stopień złamania = tygodnie bez takiej przerwy / tygodnie pracy.
- Trzecie ograniczenie z Kodeksu (11 h odpoczynku) już jest w katalogu jako "Odpoczynek między zmianami" (dobra praktyka, domyślnie włączona i miękka); kierownik może ją oznaczyć "bez wyjątków".

Założenia:
1. Zasady dotyczą wszystkich osób lokalu, bo zasady są ustawiane per lokal. Kto chce limitów tylko dla wybranych osób, napisze to prośbą tekstem (etap 10).
2. Istniejące dane: kolumna `contract` jest po prostu usuwana. Decyzja Piotra po merge'u (13.11.2026): obie zasady są dobrą praktyką, więc nowe lokale zaczynają z nimi włączonymi (miękkie), a migracja `rules.0004` dopisuje je na koniec listy w istniejących grupach i lokalach bez grupy (jak `experience_mix`). Nie da się ich włączyć tylko tam, gdzie była umowa o pracę, bo tej informacji już nie ma.
3. Nazwy parametrów (`max_hours`, `rest_hours`) różnią się od `hours` z "Odpoczynku między zmianami", bo ekran zasad podpisuje pola po nazwie parametru.

## 18. Etap 9: oddawanie zmian, powiadomienia, historia przypisań

- Logika: `apps/marketplace/services.py` (oddanie, "Biorę", wycofanie, zatwierdzenie, odrzucenie, oddania po nowej publikacji), `apps/notifications/services.py` (zapis powiadomień i polskie zdania budowane przy odczycie z rodzaju i danych, więc poprawka tekstu działa też dla starych powiadomień).
- Ekrany: w "Mój grafik" przycisk "Oddaj" przy każdej zmianie (arkusz z wyjaśnieniem, że do decyzji kierownika to nadal moja zmiana, i "Zostaję na tej zmianie"), sekcja "Zmiany do wzięcia" z "Biorę" / "Jednak nie biorę" (od 14.11.2026 "Weź zmianę" / "Zrezygnuj", a "Zostaję na tej zmianie" to "Jednak nie oddaję", patrz 15a pkt 10); trzecia zakładka "Powiadomienia" z licznikiem nowych (`/powiadomienia`); u kierownika "Oddane zmiany" (`/kierownik/oddane-zmiany`) z licznikiem chętnych w nagłówku; w arkuszu zmiany na karcie "Grafik" "Historia tej zmiany".
- Licznik i listy odświeżają się co minutę (bez websocketów, jak w założeniu 8 z sekcji 7).

Założenia:
1. Kto dostaje powiadomienie o oddanej zmianie: każda aktywna osoba firmy (z każdego lokalu) poza oddającym, która ma stanowisko o tej samej nazwie (stanowiska są per lokal, więc "Sprzedawca" w Wieliczce i "sprzedawca" w Skawinie to to samo; wielkość liter bez znaczenia) i dla której walidator nie znajduje nowego twardego problemu po wpisaniu jej na tę zmianę w opublikowanym grafiku: "nie mogę", inna zmiana w tym czasie (także w innym lokalu), zasady "bez wyjątków". Od PR #11 dzień bez zaznaczenia znaczy "mogę", więc "zaznaczyły dyspozycyjność" rozumiem jako "nie zaznaczyły nie mogę".
2. Sprawdzenie powtarza się przy "Biorę", na liście kierownika (przy każdym chętnym widać powód, dla którego już nie może) i przy zatwierdzeniu, bo grafik i kalendarz mogą się zmienić. "Zmiany do wzięcia" pokazują tylko oddania, które dana osoba może wziąć teraz.
3. Oddać można tylko własną zmianę z opublikowanego grafiku, która się jeszcze nie zaczęła. Oddanie zaczętej zmiany wygasa samo. Kierownik decyduje o chętnych w lokalach, którymi zarządza (właściciel o wszystkich); powiadomienie "ktoś chce wziąć" dostają właściciele i kierownicy tego lokalu.
4. Zatwierdzenie zmienia przypisanie w opublikowanej wersji w miejscu (bez nowej wersji; nowa wersja na każde oddanie zastąpiłaby albo zdublowała szkic, który kierownik może właśnie poprawiać, a zmianę i tak zapisuje historia przypisań), oznacza je jako ręczne i przypięte (ponowne układanie nie cofnie uzgodnionej zamiany; przypięcie potwierdził Piotr 13.11.2026) i "z innego lokalu", gdy biorący jest spoza lokalu. Jeśli okres ma nowszy szkic i ta osoba nadal jest w nim na tej zmianie, szkic też się zmienia. Historia: `AssignmentEvent` z powodem "oddana zmiana" i osobą, która zatwierdziła. Pozostali chętni dostają odmowę.
5. Osoba pożyczona z innego lokalu "ma" stanowisko lokalu, jeśli ma stanowisko o tej samej nazwie (`problem_builder`), więc grafik z taką osobą przechodzi walidator i daje się opublikować.
6. Nowa publikacja okresu: otwarte oddania idą za zmianą, jeśli oddający nadal na niej jest; w przeciwnym razie wygasają, a oddający i chętni dostają powiadomienie.
7. Otwarcie "Powiadomień" oznacza pokazane jako przeczytane; do następnego odświeżenia zostają oznaczone "Nowe". Oznaczanie działa też w trybie tylko do odczytu (dopisane do wyjątków w spec.md: inaczej licznik nowych nie dałby się wyzerować); oddawanie i branie zmian nie działa.
8. Pełne zamiany dwóch osób (`AssignmentEvent.Reason.SWAP`) nadal na później; model oddań i historia ich nie blokują.
9. Kierownicy lokalu dostają powiadomienie już przy oddaniu zmiany (z liczbą osób, które mogą ją wziąć; przy zerze wprost, że oddający nadal ma tę zmianę), żeby oddanie bez chętnych nie czekało po cichu do dnia zmiany.
10. Gdy zmianę bierze osoba z innego lokalu, kierownicy jej lokalu domowego (jeśli nie prowadzą też lokalu ze zmianą) dostają powiadomienie po zatwierdzeniu. Panel kierownika ma w nagłówku link "Powiadomienia" z licznikiem nowych.

Po przeglądzie Prelinta (PR #13), do sprawdzenia w pilocie: czy powiadomienie do całej firmy (w danych demo jedna zmiana trafiła do 34 osób) nie jest za głośne i czy nie lepiej najpierw lokal domowy, a po kilku godzinach reszta; czy nazwy stanowisk w lokalach naprawdę się pokrywają (jeśli nie, potrzebne jawne powiązanie stanowisk); czy potrzebne jest przypomnienie oddającemu i kierownikowi na dzień przed zmianą bez chętnych (dziś tylko powiadomienie przy oddaniu).

## 19. Wdrożenie na jeden serwer VPS (13.11.2026)

Decyzja Piotra z 13.11.2026: zamiast wersji demo na GitHub Pages stawiamy pełny serwis na tanim VPS. Instrukcja: `docs/deploy.md`.

- `docker-compose.prod.yml` dokłada do `docker-compose.yml` porty 80 i 443 dla Caddy i zdejmuje port bazy z hosta. Włącza go `COMPOSE_FILE` w `.env` na serwerze (`.env.production.example`), więc lokalne `docker compose up` działa bez zmian.
- `deploy/setup-server.sh` (pierwsze uruchomienie, można powtarzać), `deploy/update.sh` (nowa wersja z `main`), `deploy/auto-update.sh` (cron co 5 minut), `deploy/backup.sh` (codzienny zrzut bazy z crona, 14 dni).
- Sekrety (`DJANGO_SECRET_KEY`, hasło bazy) losuje skrypt na serwerze; adresu serwera, haseł i kluczy nie ma w repozytorium.

Założenia:
1. Bez własnej domeny serwis działa pod nazwą `<ip>.sslip.io` z certyfikatem pobranym przez Caddy, bo logowanie wymaga HTTPS (ciasteczko sesji tylko po szyfrowanym połączeniu). Własna domena to zmiana trzech wartości w `.env`.
2. Bramka SMS nadal niepodłączona: kody logowania są w logu serwera, więc do czasu jej podłączenia serwis jest do testów Piotra, nie dla pracowników.
3. Wdrożenie nowej wersji jest automatyczne (decyzja Piotra z 13.11.2026: „chcę, żeby wszystko szło samo”): serwer co 5 minut sprawdza gałąź `main` i sam uruchamia `deploy/update.sh` (`deploy/auto-update.sh` z crona). Serwer pobiera kod sam, więc w GitHubie nie ma klucza do serwera. Każdy merge do `main` trafia od razu na serwis; warunek przejścia na kontrolowane wdrożenia (ręczne albo z gałęzi wydań): zanim zostanie podłączona bramka SMS, razem z kopią bazy poza serwerem (z przeglądu PR #16). Nieudane wdrożenie jest ponawiane raz; po drugiej porażce serwer może wysłać wiadomość na adres z `DEPLOY_ALERT_URL` (opcjonalne, np. ntfy).
4. Kopie bazy leżą na tym samym serwerze; kopia poza serwerem to osobny krok przed pilotażem.
5. `SOLVER_WORKERS=2` na serwerze (2 rdzenie), limit 30 s bez zmian.

## 20. Etap 10: asystent (Claude; od 21.11.2026 także OpenRouter, sekcja 30) i przyjęte założenia

Co powstało:

- `apps/assistant/`: `llm.py` (jedyny moduł, który woła model językowy; stan z etapu 10: Anthropic Python SDK, `messages.parse` ze schematem Pydantic, model z `ANTHROPIC_MODEL`, domyślnie `claude-opus-5-5`; od 21.11.2026 domyślnie OpenRouter z `deepseek/deepseek-v4.1-flash`, a Claude tylko przy samym `ANTHROPIC_API_KEY`, sekcja 30), `readings.py` (wspólna struktura "jedno życzenie o jednej osobie": sprawdzanie, daty i dni tygodnia, zdanie po polsku), `services.py` (co wysyłamy, jak sprawdzamy odpowiedź, zapis), `tasks.py` (kolejka `default`), `api.py`, modele `ManagerInstruction` i `AssistantCommand`.
- Prośby pracowników: `POST /me/requests` zapisuje prośbę i zleca zadanie `assistant.interpret_text_request` w jednej transakcji. Worker pyta model (wtedy Claude, od 21.11.2026 domyślnie DeepSeek przez OpenRouter) i zapisuje interpretację tylko wtedy, gdy typ, osoba, zmiana i dni dają się sprawdzić na danych lokalu, a pewność jest co najmniej `ASSISTANT_MIN_CONFIDENCE` (0,6). W każdym innym przypadku (także błąd sieci, limit, odmowa) prośba ma status "do decyzji menedżera" bez interpretacji i w generatorze jest typu "inne". `PATCH /me/requests/{id}`: nowa treść (czytana od nowa) albo `understood: false` ("nie o to mi chodziło").
- Polecenia kierownika: `POST /locations/{id}/assistant-commands` (zapis + zadanie `assistant.plan_assistant_command`), `GET /assistant-commands/{id}` (odpytywanie co 1,5 s), `POST /assistant-commands/{id}/apply`, `POST /assistant-commands/{id}/dismiss`, `GET /locations/{id}/instructions`, `PUT /locations/{id}/instructions/order`, `DELETE /instructions/{id}`. Plan jest sprawdzany przez `services.check_plan`: wszystko, czego nie ma w lokalu, wypada z notatką; zdania dla kierownika układa aplikacja; zmiany zasad przechodzą przez ten sam kod co ekran "Zasady" (`save_rules`) i ten sam podgląd skutku.
- Plan dotyczący osoby pokazuje wykonanie na ostatnim grafiku. Domyślne miejsce dopisania jest ustalane przy zatwierdzeniu. Limit tygodniowy jest liczony w tygodniach kalendarzowych. Wyjaśnienie zmiany porównuje aktualny przydział z wykonalną zamianą przy pozostałych przydziałach bez zmian.
- Silnik: `Request.by_manager` i `rank`. Polecenia kierownika o osobach trafiają do `Problem` jako prośby z `by_manager=True`; ich waga to `rule_weight(miejsce)` i liczą się do oceny "zasady menedżera" oraz do części `manager_share` w celu solvera. `WeightProfile.level_weights["employee_budget"]` (12 = jedna "bardzo ważna" + jedna "ważna"): suma wag próśb tekstem jednej osoby jest skalowana w dół do budżetu.
- Ekrany: "Zasady" lokalu zaczynają się od "Powiedz asystentowi, co zmienić" (pole, plan z "Zatwierdź zmiany" / "Odrzuć", lista "Twoje polecenia o osobach" ze strzałkami i "Usuń"); "Kiedy mogę" pokazuje pod prośbą "Tak to zrozumieliśmy: …" z "Nie o to mi chodziło"; "Dyspozycje" kierownika pokazują interpretację; "Grafik" pokazuje osobno niespełnione polecenia kierownika i odsyła do asystenta.
- Testy: atrapa funkcji `llm.read_request` / `llm.plan_command`, a sama ścieżka SDK na sztucznym transporcie HTTP (bez sieci i bez klucza).

Założenia:

1. ~~Jedna prośba = jedna sprawa. Tekst z kilkoma życzeniami naraz asystent oznacza jako "inne" i czyta go kierownik.~~ Zmienione 19.11.2026 ("Asystent z dostępem do API"): jedna wiadomość może mieć pytanie i do 3 preferencji, każda jest osobną prośbą dla generatora (`<pk>`, `<pk>:2`, …); więcej niż 3 albo część nie do sprawdzenia czyta kierownik.
2. Asystent kierownika działa na poziomie lokalu (ludzie należą do lokalu). Zasady grupy ustawia się ręcznie na ekranie zasad grupy. Powiązanie lokali poleceniem ("ułóż te dwa razem") zostaje na później; silnik to umie, ale nie ma jeszcze na to ustawienia.
3. Polecenia o osobach są miękkie (generator nie zostawi przez nie zmiany bez obsady). "Bez wyjątków" mają tylko zasady z katalogu.
4. Polecenia o osobach mają własną kolejność, osobną od listy zasad: polecenie na miejscu k waży tyle, co zasada na miejscu k. Jedna wspólna lista zasad i poleceń to możliwy następny krok.
5. Polecenie z samymi datami, które minęły, zostaje na liście z etykietą "minęło" i nie wpływa na grafik; kierownik je usuwa.
6. Limity: od 20.11.2026 domyślnie wyłączone (0 = bez limitu, decyzja Piotra). Można je włączyć w `.env`: `ASSISTANT_COMMANDS_MONTHLY_LIMIT` (polecenia firmy w miesiącu; wcześniej domyślnie 400, a do 19.11.2026 200), `TEXT_REQUESTS_PER_PERIOD` (prośby jednej osoby na okres; wcześniej 10; liczą się tylko `new`, `interpreted` i `needs_manager`) i `ASSISTANT_MESSAGES_PER_DAY` (wiadomości osoby na dobę; wcześniej 40). Tryb tylko do odczytu blokuje polecenia jak każdą zmianę.
7. Nie włączamy automatycznego przełączania na inny model po odmowie; odmowa lub ucięta odpowiedź to po prostu "do decyzji menedżera" / "asystent nie dał rady".
8. (Od 21.11.2026 domyślnie OpenRouter z DeepSeek V4.1 Flash, sekcja 30; to, co niżej, dotyczy drogi przez Claude.) Model domyślny to `claude-opus-5-5`; do taniej, masowej interpretacji próśb można ustawić `ANTHROPIC_MODEL=claude-haiku-5-5` bez zmian w kodzie. Głębokość myślenia ustawia `ANTHROPIC_EFFORT` (`low`, `medium`, `high`, `xhigh`, `max`; domyślnie `low`, pusta wartość = domyślny poziom modelu).

Uzupełnienie 15.11.2026 (po teście Piotra na serwerze, dwie prośby bez interpretacji):

- Nowy typ prośby i polecenia `chce_pracowac` (`RequestType.WANT_WORK`): daty lub dni tygodnia, `min_days` (w ilu z tych dni; brak = we wszystkich) i `shifts_per_day` (1–3). Stopień złamania = brakujące dni / `min_days`, gdzie dzień liczy się, gdy osoba ma w nim co najmniej `shifts_per_day` zmian. W solverze kara za każdy brakujący dzień. Dwie zmiany jednego dnia da się spełnić tylko wtedy, gdy zasady odpoczynku na to pozwalają; jeśli „Odpoczynek między zmianami” jest „bez wyjątków”, prośba zostanie niespełniona.
- `TextRequest.unread_reason` (`off` / `unsure` / `failed`): kierownik widzi, dlaczego prośba nie ma interpretacji. `POST /requests/{id}/reread` (`reread_request`) daje asystentowi prośbę, która przyszła przy wyłączonym asystencie albo przy błędzie. Migracja oznacza istniejące prośby bez interpretacji jako `off`.
- Lista pomyłek asystenta (pomysł Piotra 15.11.2026): `TextRequest.assistant_answer` i `AssistantCommand.assistant_answer` trzymają nieużytą odpowiedź modelu z powodem (`why`) albo błąd. Superadmin widzi je w panelu administratora, a `manage.py assistant_misses --days N` wypisuje CSV: prośby do decyzji kierownika, wiadomości odrzucone jako niezwiązane z pracą (od 19.11.2026) oraz polecenia, które skończyły się błędem, pytaniem, uwagą albo brakiem zmian. Odpowiedzi na pytania nie są pomyłkami. Plik ma treść pisaną przez ludzi, więc jest tylko dla superadmina.
- Prośbę, która przyszła przy wyłączonym asystencie, kierownik może dać asystentowi, ale pracownik dostaje wtedy powiadomienie `request_to_assistant` (pracował przy informacji, że czyta tylko kierownik).

## 21. Stopień per stanowisko i doświadczeni w obsadzie (13.11.2026)

Decyzja Piotra po przeglądzie konkurencji (raport: https://claude.ai/artifact/PyE6iDjvz9cUqPWGqXnL8c). Poziomy doświadczenia per stanowisko i wymóg poziomu na miejscu w obsadzie ma HotSchedules; Kadromierz każe rozbijać stanowisko na "młodszy" i "starszy".

1. `PositionExperience` (employee, position, level): tylko wyjątki od `EmployeeProfile.experience`. Wiersz równy stopniowi domyślnemu nie jest zapisywany; odznaczenie stanowiska usuwa jego wyjątek. Istniejące dane nie wymagają migracji danych.
2. `StaffingRule.experienced` i `StaffingException.experienced` (domyślnie 0, nie więcej niż `count`): ile osób z obsady ma być doświadczonych. Wyjątek na datę ma własną wartość; formularz wyjątku zostawiony pusty przyjmuje liczbę ze zwykłej obsady tego dnia (nie więcej niż liczba osób), żeby wymóg nie znikał po cichu. Wolne miejsce z powodu wymogu jest nazwane w wyjaśnieniu zmiany ("obsada wymaga tu doświadczonej osoby").
3. Silnik: `Employee.experience_by_position` i `Employee.level(position)`; `Slot.needs_experienced` na pierwszych N miejscach grupy (lokal × dzień × typ zmiany × stanowisko). Wymóg liczony na grupę, nie na miejsce: liczba mniej doświadczonych osób w grupie nie może przekroczyć liczby miejsc bez wymogu. Dzięki temu nie ma znaczenia, na którym miejscu grupy stoi doświadczona osoba, a niepełna obsada nie jest błędem, dopóki zostaje miejsce dla doświadczonej.
4. Walidator: twarde naruszenie `experience` (nie zasada katalogu, bo wynika z obsady). Twarde dla generatora i oddawania zmian; kierownik może je złamać ręcznie i opublikować grafik z ostrzeżeniem (jedyny taki wyjątek, `editing.MANAGER_MAY_BREAK`, sekcja 26, punkt 7). Solver: to samo jako ograniczenie; nigdy nie daje sprzeczności, bo miejsce może zostać luką. Przypięcie, które samo łamie wymóg, zmniejsza go przy ponownym układaniu (od 19.11.2026, sekcja 26, punkt 7; wcześniej było zgłaszane jak inne konflikty przypięć). Dni, które minęły, zachowują opublikowane zmiany; od 19.11.2026 zapisana zmiana pamięta wymóg (`Shift.needs_experienced`).
5. `experience_mix` i wyjaśnienia liczą stopień na stanowisku danej zmiany. Osoba pożyczona z innego lokalu ma stopień ze stanowiska o tej samej nazwie.
6. API: `EmployeeOut.position_experience` (stopień na każdym stanowisku osoby) i `EmployeeIn.position_experience`; komórki obsady i wyjątki mają pole `experienced`. Pracownik nadal nie widzi żadnego stopnia.
7. Ekrany: w arkuszu pracownika z co najmniej dwoma stanowiskami "Inny stopień na którymś stanowisku"; w obsadzie pole "w tym doświadczonych" przy komórce i przy wyjątku.
8. Poza zakresem: opiekun dla nowej osoby (etap 10, polecenie do asystenta), podpowiedź awansu z godzin, etykiety uprawnień z datą ważności.
9. Ostrzeżenie przed układaniem (decyzja Piotra z 15.11.2026): `apps/staffing/shortage.py` liczy dla okresu, na których stanowiskach największy wymóg "w tym doświadczonych" na jednej zmianie (zwykła obsada dni tygodnia z okresu i wyjątki na daty) przekracza liczbę aktywnych osób lokalu z tym stanowiskiem i stopniem "doświadczony" na nim. Wynik jest w `PeriodOut.experienced_short` i `PeriodSummaryOut.experienced_short` (stanowisko, ile potrzeba, ile jest, pierwszy dzień i zmiana z tym wymogiem). Arkusz "Ułóż grafik" pokazuje to jako ostrzeżenie i nie blokuje układania. Założenia: liczymy tylko pewny brak (jedna zmiana, bez sumowania zmian jednego dnia, bez dyspozycji i urlopów), więc brak ostrzeżenia nie gwarantuje pełnej obsady; osoby z innych lokali nie są wliczane, bo generator sam ich nie pożycza.

## 22. Poprawki po audycie świeżym okiem (15.11.2026)

Trzech testerów bez znajomości wymagań (pracownik na telefonie, kierownik kilku lokali, tester błędów i bezpieczeństwa)
zgłosiło 32 uwagi; Piotr zatwierdził wszystkie. Raport: `/mnt/project-files/audyt/audyt-swiezym-okiem.md`.
Poprawki w czterech PR-ach (czwarty: dyspozycje w dwóch przedziałach dnia). Pierwszy (błędy i bezpieczeństwo) przyjmuje te założenia:

- „Mój grafik” pokazuje dni do końca opublikowanego okresu lokalu domowego (`published_until`), więc wolny ostatni dzień
  też widać.
- Okres grafiku zaczyna się najwcześniej rok temu i kończy najpóźniej za dwa lata; termin dyspozycji najwyżej 120 dni
  przed początkiem; wyjątek w obsadzie najwyżej dwa lata od dziś. Chroni przed literówką w roku (0001, 9999), która psuła
  obliczenia dat.
- Błąd serwera (odpowiedź bez `detail`, 5xx) nie każe sprawdzać internetu; 401 w trakcie pracy przenosi do logowania.
- Ekran kodu SMS przetrwa odświeżenie strony (numer i czasy w `sessionStorage` karty, do wygaśnięcia kodu).
- Publikacja blokuje najpierw firmę, potem okres, jak układanie grafiku (bez zakleszczeń).
- CSV godzin: nazwy zaczynające się od `= + - @` dostają apostrof (Excel nie wykona formuły).
- Kody dostępu: sprawdzenie limitu i zapis próby pod blokadą per osoba i per IP (równoległe próby nie omijają limitu).
- Rejestracja: jeden adres IP może w godzinę wysłać kody najwyżej na 5 nowych numerów (`REGISTER_NUMBERS_PER_IP_PER_HOUR`); komunikat podpowiada inną sieć (wspólne wifi).
- `/api/docs` i `/api/openapi.json` tylko przy `DJANGO_DEBUG=1`; logowanie do admina: najwyżej 10 nieudanych prób na adres
  na godzinę (`ADMIN_LOGIN_FAILURES_PER_IP_PER_HOUR`, licznik w pamięci procesu).

Drugi PR (ekrany pracownika, punkty 12–17):

- „Kiedy mogę”: na niskim ekranie (do 800 px wysokości) pasek wyboru stanu jest niższy, a położony telefon
  (do 500 px) nie ma przyklejonych pasków, bo zabierały cały kalendarz.
- Okno godzin dłuższe niż 12 h przez północ (np. 20:00–16:00) wymaga potwierdzenia i ma przycisk „Zamień”;
  zmiana w ustawieniach lokalu dłuższa niż 12 h wymaga zaznaczenia „Tak, ta zmiana trwa … godz.”.
- Kto może wziąć oddaną zmianę, liczymy jak dotąd (stanowisko o tej samej nazwie w firmie + walidator). Audyt pokazał,
  że koledzy z lokalu częściej odpadają, bo mają już opublikowany grafik (np. zmiana w tym samym czasie, piąty dzień
  z rzędu), a osoby z lokali bez grafiku wyglądają na wolne. Dlatego oddający widzi teraz, ile osób jest z jego lokalu,
  a ile z innych, i dostaje powiadomienie `offer_claimed`, gdy ktoś się zgłosi.
- Ekran kodu: stary błąd znika po pierwszej nowej cyfrze, wpisany kod zostaje; zamiast bladego wyłączonego przycisku
  jest licznik „Nowy kod możesz dostać za …”. „Weź zmianę” i „Usuń prośbę” pytają jeszcze raz.
- Hipotezy do sprawdzenia w pilotażu (uwagi Prelinta do PR #24): czy osoby z innych lokali chcą powiadomień o oddanych
  zmianach (jeśli nie: najpierw własny lokal, potem firma); czy próg 12 h dla ostrzeżenia o długim oknie pasuje
  wszystkim (to tylko pytanie o zamienione godziny, nie limit; lokal z dłuższymi zmianami potwierdza je raz).

Trzeci PR (ekrany kierownika, punkty 18–32):

- Osobiste maksimum godzin (`personal_max_hours`) ma parametr `tolerance_pct` (domyślnie 10, od 0 do 50), jest domyślnie
  „bez wyjątków” i należy do zasad dobrej praktyki (nowy lokal dostaje ją włączoną). Migracja `rules.0005` robi ją twardą
  z zapasem 10% tam, gdzie już była, i dopisuje na końcu listy tam, gdzie jej nie było. Zwykła (miękka) wersja liczy
  karę dopiero ponad maksimum z zapasem. Zasada robi się twarda także w działających lokalach (decyzja Piotra
  15.11.2026); na dziś to tylko dane demo, a przed pilotażem trzeba uprzedzić kierowników, że osoby z maksimum mogą
  zostawić więcej pustych zmian i że zasadę da się zmienić na zwykłą w „Zasady”.
- Dni zamknięcia (`staffing.LocationClosure`: lokal, data, powód): generator nie tworzy w nie żadnych miejsc, ważniejsze
  niż wyjątek w obsadzie. Dni, które minęły, zostają jak w opublikowanym grafiku. Gdy szkic ma jeszcze kogoś w dzień zamknięcia
  (`ClosureOut.in_draft`), lista mówi, że trzeba ułożyć grafik od nowa.
- Pustą zmianę można przypiąć („Zostaw pustą na stałe”): `Problem.pinned` przyjmuje `None`, solver trzyma ją pustą,
  walidator zgłasza wpisanie kogoś mimo przypięcia. Ręczne wpisanie osoby zdejmuje przypięcie jak dotąd.
- Zmiana, której nikt nie może wziąć, nie dostaje przycisku „Wpisz mimo to”: wpisanie łamiące zasady bez wyjątków
  i tak byłoby odrzucone, a grafiku z takim błędem nie da się opublikować. Okienko mówi, co można zrobić zamiast tego
  (wyjątek w obsadzie, zasada zwykła zamiast „bez wyjątków”, stanowisko komuś jeszcze, zostawić pustą).
- „Po terminie” liczy się od późniejszej z dwóch chwil: początku dnia po terminie albo chwili ustawienia terminu
  (`SchedulePeriod.deadline_set_at`; puste w starszych okresach). Termin wpisany wstecz nie robi więc z wszystkich spóźnialskich.
- Imię i nazwisko pracownika poprawia kierownik w „Zmień”, tylko gdy konto tej osoby nie należy do innej firmy. Numeru
  nie: to login, więc zgodnie ze spec zmienia go superadmin (sesje wygasają, zaproszenia trzeba wysłać ponownie).
- Lista pracowników podaje `draft_shifts` (zmiany od dziś w nieopublikowanym szkicu); wyłączenie osoby z takimi
  zmianami pokazuje ostrzeżenie.
- Karta lokalu bez stanowisk, zmian, obsady lub pracowników (`setup_missing`) pokazuje kroki z linkami. Gdy firma ma jedną
  grupę, nowy lokal domyślnie do niej trafia, a pole mówi, że lokal w grupie używa jej zasad.
- Menu kierownika: „Lokale” i „Pracownicy” (wszyscy z lokali kierownika, z wyszukiwarką; zmiany w lokalu osoby);
  „Mój grafik” tylko dla kierownika, który sam pracuje na zmianach (`works_shifts` w `/me`). Na telefonie menu to jeden
  przewijany wiersz.
- Wynik grafiku zaczyna się jednym zdaniem, które mówi o faktach („Wszystkie zmiany obsadzone…”), bez oceny „dobry”; link „Napisz polecenie asystentowi” zmienia się na „Zmień zasady
  lokalu”, gdy asystent jest wyłączony. Po 2 minutach układania ekran mówi „Trwa dłużej niż zwykle”.
- „Godziny” na pustym miesiącu proponują ostatni miesiąc z godzinami (`latest_month`). Teksty: „mogą pracować”,
  formy bez „(a)”, „Ułożyć grafik dla lokalu …?”, przykłady stanowisk nie tylko z piekarni.
- Hipotezy do sprawdzenia w pilotażu (uwagi Prelinta do PR #25): czy kierownicy kilku lokali chcą wpisywać dni
  zamknięcia raz dla całej grupy (dziś każdy lokal osobno) i czy w nagłej sytuacji proszą o jednorazowy wyjątek od
  zasady „bez wyjątków” zamiast zmiany zasady dla całego lokalu.

Czwarty PR (prośba Piotra z 15.11.2026: dyspozycja w dwóch przedziałach dnia z „lub/albo”):

- `AvailabilityDay` ma drugi przedział (`from_time_2`, `to_time_2`, oba albo żaden, tylko gdy jest pierwszy) i `one_shift`.
  „Lub” (`one_shift=False`): zmiana pasuje, gdy mieści się w którymkolwiek przedziale, można dostać dwie. „Albo”
  (`one_shift=True`): dodatkowo najwyżej jedna zmiana zaczynająca się tego dnia, licząc zmiany z innych lokali
  (twarde: walidator `Code.ONE_SHIFT`, solver `sum ≤ 1`). Przy „nie mogę” oba przedziały są zakazane, „albo” nic nie znaczy.
- „Albo” bez drugiego przedziału nie jest zapisywane. Zapis dnia bez drugiego przedziału go czyści.
- Powtarzanie co tydzień (`/me/availability/pattern`, na razie bez ekranu) ustawia sam stan bez godzin, jak dotąd;
  wzorce z godzinami i dwoma przedziałami to następny krok, jeśli pilotaż pokaże taką potrzebę. Kopiowanie
  z poprzedniego miesiąca przenosi oba przedziały.
- Tabela dyspozycji kierownika pisze „6–10/16–22”, a przy „albo” dodatkowo słowo „albo” w komórce i w legendzie.
- Hipotezy do sprawdzenia w pilotażu (uwagi Prelinta do PR #27): czy pracownicy rozumieją różnicę „lub” / „albo”
  i jak często „albo” zostawia zmiany bez obsady.
- Dzień zamknięcia mówi też, gdy opublikowany grafik ma kogoś w ten dzień (`ClosureOut.in_published`), i przypomina,
  że ułożenie od nowa zostawia tylko przypięte zmiany.

Po teście Piotra 15.11.2026 (osobny PR):

- Prośbę tekstem można napisać zawsze. Bez okresu należy do miesiąca na ekranie (`TextRequest.month`, `period` puste;
  w bazie zawsze dokładnie jedno z nich). Liczy się w każdym okresie lokalu domowego osoby, który obejmuje ten miesiąc
  (`TextRequest.for_periods`): kierownik widzi ją na liście próśb okresu, a generator bierze tylko dni z okresu.
  Asystent czyta ją z datami całego miesiąca. Można ją zmienić albo usunąć do końca tego miesiąca.
  Pracownik widzi ją też w okresie, który obejmuje ten miesiąc. Do pilotażu (uwaga Prelinta do #28): czy kierownik
  potrzebuje znaku, że prośba miesięczna zmieniła się po ułożeniu szkicu.
- Caddy: `index.html` z `Cache-Control: no-cache`, pliki z `/assets` (z hashem w nazwie) na rok. Otwarta karta, która po
  wdrożeniu nie znajdzie starego pliku ekranu, przeładowuje się sama (`vite:preloadError`). Przyczyna: Piotr po wdrożeniu
  #27 widział jeszcze starą wersję okienka dnia.
- Polecenia kierownika dla asystenta nie są przypięte do okresu (tak było od etapu 10), ale asystent dostawał tylko
  najbliższy okres i prompt kazał mu trzymać daty w okresie. Teraz kontekst wymienia okresy od dzisiaj i mówi wprost,
  że polecenie może dotyczyć dowolnego przyszłego dnia, także miesiąca bez okresu; generator weźmie je, gdy kierownik
  założy ten okres (zgłoszenie Piotra 17.11.2026). Plan mówi wtedy kierownikowi, że polecenie zadziała po założeniu
  okresu na te dni; polecenie tylko o dniach ponad rok naprzód jest pomijane z uwagą (jak w kalendarzu dyspozycji).

## 23. Przejęcie oddanej zmiany bez zatwierdzania (15.11.2026)

Prośba Piotra: zasada lokalu, przy której "Weź zmianę" od razu przenosi oddaną zmianę, bez kierownika.

- Ustawienie `Location.handover_without_approval` (domyślnie wyłączone), zmieniane przez `PATCH /api/locations/{id}`;
  przełącznik "Przejęcie oddanej zmiany bez zatwierdzania" na dole ekranu "Zasady" lokalu, zapisywany od razu.
  To nie jest zasada z `engine/rules_catalog.py`: katalog opisuje ocenę grafiku przez walidator i solver, a to
  ustawienie zmienia tylko tok oddawania zmian. Dlatego nie ma go w grupie lokali (każdy lokal osobno) ani w podglądzie
  "Co się zmieni?".
- Przy włączonym ustawieniu `claim_offer` sprawdza osobę tak samo jak dotąd (walidator, bez nowych twardych problemów)
  i od razu wykonuje to samo co zatwierdzenie (`_hand_over`): przeniesienie w opublikowanym grafiku i w najnowszym
  szkicu, przypięcie, `AssignmentEvent` z powodem "oddana zmiana", gdzie "kto" to sam biorący, nowe wyniki grafiku.
  `ShiftClaim.auto_approved` zaznacza takie przejęcie (na liście "Oddane zmiany": "Wzięta bez zatwierdzania").
- Powiadomienia: biorący `claim_taken`, oddający `offer_taken_auto`, kierownicy lokalu `handover_done`, kierownicy
  lokalu domowego osoby z innego lokalu `borrowed` (z dopiskiem, że bez zatwierdzania).
- Założenie: jeśli ktoś czekał już na decyzję kierownika, zanim ustawienie włączono, kolejne "Weź zmianę" przy tym
  oddaniu też czeka na kierownika (pierwszy chętny nie traci miejsca). Nowe oddania działają już bez zatwierdzania.
- Teksty dla pracownika zależą od ustawienia lokalu zmiany (`at_once`, `handover_at_once`): "Pierwsza osoba, która ją
  weźmie, dostaje ją od razu", "Tak, biorę", "Zmiana jest Twoja".
- Po przeglądzie Prelinta (PR #29): gdy ustawienie jest włączone, a w lokalu nadal czekają zgłoszenia sprzed włączenia,
  pod przełącznikiem widać, ile oddanych zmian czeka na decyzję w "Oddane zmiany" (żeby nie utknęły). Do decyzji Piotra:
  czy osoba z innego lokalu też bierze od razu (dziś tak, a jej kierownik dostaje powiadomienie). Do sprawdzenia
  w pilocie: czy kierownicy chcą tego ustawienia dla całej grupy lokali i czy "kto pierwszy, ten lepszy" jest
  sprawiedliwe (np. osoba blisko limitu godzin).

## 24. Ręczne zarządzanie oddawaniem i zamianami przez kierownika (18.11.2026)

Prośba Piotra: oddawanie zmian jest ważne, a kierownik może chcieć zrobić to ręcznie.

- Logika: `apps/marketplace/services.py`, sekcja "the manager's own changes": `manager_reassign` (inna osoba na
  opublikowanej zmianie, także pustej), `manager_swap` (dwie osoby zamieniają się zmianami, historia z powodem
  "zamiana"), `offer_shift(by_manager=...)` (kierownik szuka chętnych w imieniu pracownika), `manager_close_offer`
  (koniec oddawania, zmiana zostaje u oddającego; status oddania "rejected").
- Endpointy: `GET /locations/{id}/handover-shifts` (opublikowane zmiany lokalu: 14 dni wstecz, 62 dni naprzód),
  `GET /assignments/{id}/handover-candidates`, `POST /assignments/{id}/reassign`, `POST /shift-swaps/check`,
  `POST /shift-swaps`, `POST /assignments/{id}/offer`, `POST /offers/{id}/close`. Wszystkie tylko dla kierownika lokalu.
- Ekran: w "Oddane zmiany" przy aktywnym oddaniu "Wybierz osobę sam" i "Zakończ oddawanie"; pod listą sekcja
  "Zmień obsadę sam" (lokal, dzień, zmiana, potem arkusz z osobami, "Zamień z inną zmianą" i "Poszukaj chętnych").

Decyzje i założenia:

1. Kierownik może pominąć zastrzeżenia walidatora (`force`). Na liście osób najpierw są ci, którzy mogą przyjść
   (chętni z "Weź zmianę" na początku), potem osoby z zastrzeżeniami i przyciskiem "Wpisz mimo to". Osoby, które
   nie pracują w lokalu zmiany, są w zwiniętej sekcji "Z innych lokali" pod listą, w tej samej kolejności (prośba
   Piotra z 20.11.2026); jej nagłówek mówi, ile osób jest w środku, ile z nich chce wziąć zmianę i ile może przyjść
   bez zastrzeżeń (uwaga Prelinta do #50: osoby z lokalu z zastrzeżeniami stoją teraz nad osobami z innych lokali,
   które mogą przyjść, więc nagłówek mówi, czy warto otworzyć). Gdy z lokalu zmiany nie ma kogo wpisać, sekcja jest
   od razu otwarta.
2. Zmiana zgodna z zasadami jest przypięta (jak zatwierdzone oddanie). Zmiana wbrew zasadom nie jest przypinana,
   bo przypięcie łamiące twardą zasadę uniemożliwia ponowne ułożenie okresu (solver zgłasza sprzeczność).
3. Na liście są osoby z tym stanowiskiem z całej firmy oraz wszyscy z lokalu zmiany (brak stanowiska to zastrzeżenie).
4. Zmiany, które już się zaczęły albo minęły, też można poprawić (ale nie wystawić do wzięcia). Powiadomienie ma
   wtedy treść "Kierownik poprawił grafik".
5. Zamiana dotyczy dwóch zmian z tego samego opublikowanego grafiku (lokal i okres). Zamiana między okresami albo
   lokalami: dwa razy "Wpisz".
6. Gdy kierownik wpisze kogoś na oddawaną zmianę, oddanie kończy się jako zatwierdzone, a pozostali chętni dostają
   odmowę. Po zamianie aktywne oddanie tej zmiany wygasa.
7. Zmiana przechodzi w opublikowanej wersji w miejscu i w najnowszym szkicu, jeśli ma tam tę samą osobę (jak przy
   zatwierdzonym oddaniu). Historia: powód "ręczna zmiana" albo "zamiana", z kierownikiem jako autorem.
8. Zamiany proponowane przez pracowników (pracownik prosi konkretną osobę) nadal na później.
## 25. Usuwanie ludzi, stanowisk, grup, lokali, okresów i powiadomień (18.11.2026)

Prośba Piotra: w aplikacji nie było jak usunąć osoby z lokalu ani powiadomienia. Przegląd pokazał też, że stanowiska
użytego w grafiku nie dało się usunąć nigdy (409), a grup, lokali i okresów w ogóle. Zasada z sekcji o historii zostaje:
zapisane grafiki i godziny nie giną, więc tam, gdzie baza blokuje usunięcie (`RESTRICT`), rzecz jest ukrywana.

- `EmployeeProfile.removed_at` i `Position.removed_at` (migracja `staffing.0007`). Usunięta osoba ma zawsze
  `is_active = false` (ograniczenie w bazie), więc wszystkie miejsca, które biorą aktywnych, pomijają ją same.
  Nazwa stanowiska jest unikalna tylko wśród nieusuniętych.
- `DELETE /employees/{id}` (`apps/staffing/removal.py`): bez przypisań usuwa profil, a przy roli pracownika także
  członkostwo i powiadomienia; z przypisaniami cofa otwarte oddania i zgłoszenia, usuwa polecenia kierownika o tej
  osobie i jej stanowiska, ustawia `removed_at`. `tenant_context` i `GET /me` nie wpuszczają usuniętego pracownika
  (404). Nowe zaproszenie przywraca profil w lokalu, który zaprasza.
- `DELETE /positions/{id}`: gdy stanowisko jest w jakiejś zmianie, ustawia `removed_at`, usuwa obsadę, wyjątki
  i powiązania z ludźmi. Zasada lokalu, która go używa, nadal blokuje (409), jak wcześniej.
- `DELETE /groups/{id}` (właściciel): przed usunięciem kopiuje zasady i profil wag grupy do lokali, które nie mają
  własnych, więc połączona lista zasad lokalu się nie zmienia.
- `DELETE /locations/{id}` (właściciel): 409, gdy lokal ma okres grafiku albo pracowników.
- `DELETE /periods/{id}`: 409, gdy jakaś wersja była opublikowana albo trwa układanie; inaczej usuwa szkice i okres.
- `DELETE /me/notifications/{id}` i `DELETE /me/notifications?company_id=`: tylko własne, bez `require_writable`.
- Ekrany: "Usuń z lokalu" w formularzu pracownika, krzyżyk i "Usuń wszystkie" w powiadomieniach, "Usuń grupę" na
  liście lokali, "Usuń lokal" w ustawieniach, "Usuń ten okres" w dyspozycjach, pytanie przed usunięciem stanowiska
  (`components/ui/confirm.tsx`).

Założenia: usunięcie osoby nie zmienia zapisanych grafików, więc jej przyszłe zmiany kierownik przenosi ręcznie albo
układa grafik od nowa (tak samo jak przy wyłączeniu z grafiku). Działało już wcześniej i zostało bez zmian: usuwanie
zmian (typów zmian), dni zamknięcia, wyjątków w obsadzie, poleceń kierownika i próśb pracownika.
## 26. Obsada wybranego dnia w kalendarzu i miejsca w edycji grafiku (18.11.2026)

Prośba Piotra: lista wyjątków (dzień, zmiana, stanowisko, każdy wpis osobno) była mało czytelna. Zamiast niej:

- Ustawienia lokalu mają kalendarz "Obsada w wybrane dni": miesiąc, w każdym dniu liczba potrzebnych osób, ikona przy
  dniu z inną obsadą niż zwykle i przy dniu zamknięcia. Wybranie dnia otwiera jego obsadę: dla każdej zmiany
  i stanowiska liczba osób (minus, plus), a po rozwinięciu doświadczeni i inne godziny. Tam też "Wróć do zwykłej
  obsady" i "Zamknij lokal w ten dzień" / "Otwórz lokal w ten dzień" (te same dni zamknięcia co na liście niżej).
- Dane zostają w `StaffingException` (bez migracji). Wiersz istnieje tylko wtedy, gdy data różni się od dnia
  tygodnia: `apps/staffing/day_staffing.py` usuwa go, gdy liczby i godziny są takie jak zwykle.
- `PUT /locations/{id}/staffing-days/{data}` zapisuje cały dzień naraz (`cells`, `note`); para pominięta wraca do
  zwykłej obsady. Zastępuje `POST /locations/{id}/staffing-exceptions` i `DELETE /staffing-exceptions/{id}`.
- Edycja grafiku (najnowszy szkic): `POST /versions/{id}/seats` dodaje puste miejsce na zmianie i stanowisku danego
  dnia, `DELETE /versions/{id}/shifts/{shift_id}` usuwa miejsce razem z osobą. Oba zapisują tę samą liczbę jako
  obsadę tej daty, więc "Ułóż od nowa" jej nie cofa. Przyciski są w arkuszu zmiany ("Ile osób na tej zmianie"),
  a w pustej komórce siatki jest "+".

Założenia:
1. Numery miejsc zostają 1…n, jak przy układaniu: gdy znika miejsce o niższym numerze, osoba z ostatniego miejsca
   (z przypięciem) przechodzi na jego numer.
2. Dni, które minęły, dni zamknięcia i opublikowane wersje: bez zmian miejsc (409). Osobę na minionym dniu można zmienić (sekcja 14).
3. Nowe miejsce bierze godziny innych miejsc tej zmiany w tym dniu, a gdy ich nie ma: godziny z obsady daty, dnia
   tygodnia albo typu zmiany. Zmiana "dowolne godziny" bez godzin: 409 z prośbą o ustawienie ich w kalendarzu.
3a. Usunięcie miejsca przechodzi przez walidator jak każda ręczna zmiana: gdy grafik złamałby przez to twardą
   regułę, której wcześniej nie łamał, jest odrzucane (409 z powodem). Po przeglądzie Prelinta (PR #39).
4. Miejsce usunięte z poprawki opublikowanego grafiku trafia do historii (`AssignmentEvent`, "ręcznie", do nikogo),
   a osoba jest na liście osób, którym zmienia się grafik (`changed_people`).
5. Kolumnę, której w grafiku jeszcze nie ma (zmiana i stanowisko bez żadnego miejsca w okresie), dodaje się
   w kalendarzu obsady i przez "Ułóż od nowa". Na telefonie pustych komórek siatki nie pokazujemy.
6. Zmiana obsady w kalendarzu nie rusza gotowych szkiców; działa od następnego ułożenia grafiku (jak dotąd).
   Po przeglądzie Prelinta (PR #39): arkusz dnia mówi to wprost, gdy data jest w okresie z ułożonym grafikiem
   (`LocationSetupOut.arranged`), także przy "Zamknij lokal w ten dzień".
7. Doświadczeni (decyzja Piotra z 19.11.2026: "kierownik może to łamać, ma władzę absolutną"). Zapisana zmiana
   pamięta, czy jej miejsce jest dla doświadczonej osoby (`Shift.needs_experienced`, migracja `scheduling.0009`
   uzupełnia je z obsady dla szkiców i opublikowanych grafików od dziś), więc walidator sprawdza wymóg także
   w zapisanym grafiku. Generator zawsze go spełnia. Ręczna zmiana, usunięcie miejsca i publikacja go nie blokują:
   `editing.MANAGER_MAY_BREAK` przenosi takie naruszenia do ostrzeżeń (`CheckOut.warnings`,
   `VersionOut.accepted_problems`, żółta ramka nad siatką), a `hard_problems` zawiera tylko to, co blokuje publikację.
   Przypięta zmiana kierownika zmniejsza wymóg przy "Ułóż od nowa" (`_keep_pinned_beginners`), zamiast przerywać
   układanie. Oddawanie zmian między pracownikami nadal wymaga doświadczonej osoby, bo tam o przejęciu decyduje
   pracownik (albo zasada lokalu bez zatwierdzania), a władza łamania wymogu należy tylko do kierownika.
## 27. Praca w kilku lokalach (19.11.2026)

Pytanie Piotra 18.11.2026: czy pracownik z jednym numerem może pracować w kilku lokalach firmy i czy jego dyspozycje oraz
zmiany są wtedy liczone między lokalami. Dotąd nie mógł (zaproszenie kończyło się odmową, generator układał tylko w lokalu
domowym). Piotr wybrał pełną pracę w kilku lokalach, jak w Kadromierzu i 7shifts: lokal główny plus lokale dodatkowe,
wspólna dyspozycyjność.

- `EmployeeProfile.extra_locations` (wiele do wielu, `related_name="extra_employees"`): lokale dodatkowe. `home_location`
  zostaje lokalem głównym (cel godzin, okresy z prośbami bez okresu, raporty). `EmployeeProfile.works_in(...)` i
  `works_in_q(...)` mówią, kto pracuje w lokalu; każde miejsce, które dotąd filtrowało po `home_location` dla listy ludzi
  lokalu, używa ich.
- Zaproszenie pracownika na numer osoby, która już pracuje w firmie, jest dozwolone, gdy lokal nie jest jej lokalem; przy
  akceptacji lokal trafia do `extra_locations`. "Dodaj mnie jako pracownika" w innym lokalu robi to samo i daje wszystkie
  stanowiska tego lokalu.
- Lista pracowników lokalu pokazuje też osoby z lokalem dodatkowym (`home_location_name`, `is_home = false`), z
  ich stanowiskami tylko z tego lokalu. `PATCH /employees/{id}` z `location_id` zmienia stanowiska i stopnie tylko w tym
  lokalu. Stopień domyślny, godziny (cel, maksimum) i wyłączenie z grafiku są wspólne, więc zmienia je tylko kierownik
  lokalu głównego (uwaga Prelinta do #45: zmiana w lokalu dodatkowym zmieniałaby grafik lokalu głównego bez wiedzy jego
  kierownika); formularz w lokalu dodatkowym ich nie pokazuje.
- Dyspozycje są zapisane na osobę i dzień, więc są wspólne. Pracownik widzi okresy i prośby o dyspozycje ze wszystkich
  swoich lokali, a ekran "Kiedy mogę" mówi, że dyspozycje są wspólne dla jego lokali (`MyCalendarOut.location_names`).
  "Wyślij kierownikowi" ("Gotowe") zaznacza dany okres i te okresy jego innych lokali, które zbierają dyspozycje i
  mieszczą się w dniach tego okresu (jeden kalendarz, więc jedno wysłanie). Dzień okresu z ułożonym grafikiem (szkic
  albo opublikowany) w którymkolwiek lokalu osoby jest zamknięty dla wszystkich jej lokali (15a pkt 9), także gdy inny
  lokal jeszcze zbiera te dni: zmiana różniłaby się po cichu od tego, czego użył tamten grafik (uwaga Prelinta do #45).
- Silnik: `Employee.extra_locations`, `Employee.works_in(location)`. Solver daje osobie tylko zmiany jej lokali; zasady
  lokalu obejmują wszystkie osoby, które w nim pracują, poza celem godzin (tylko lokal główny, żeby lokal dodatkowy,
  ułożony pierwszy, nie zabrał całego celu). Miesięczne maksimum i cel liczą też zmiany z innych lokali w dniach okresu
  (`ExternalShift`): granica w tym lokalu to `max(0, granica − godziny gdzie indziej)`, w walidatorze i solverze tak samo.
  `Request.location` mówi, do którego lokalu należy prośba (ocena lokalu liczy tylko jego prośby).
- Zmiany z innych lokali (`ExternalShift`) przy generowaniu: opublikowane wersje innych okresów oraz ich najnowszy szkic,
  jeśli jest nowszy od opublikowanej, żeby dwa lokale ułożone jeden po drugim nie dały tej samej osobie tych samych
  godzin. Walidator przy edycji i publikacji liczy tylko opublikowane zmiany innych lokali (dwie zmiany naraz to twardy
  błąd).
- Kolizja przy ręcznej zmianie (decyzja Piotra z 18.11.2026: "jak koliduje, pytanie, czy na pewno chcesz zmienić, i wtedy
  usuwa tamtą starą zmianę"): `editing.find_clashes` szuka innych zmian tej osoby w tym samym czasie: w tej wersji
  ("here"), w najnowszym szkicu ("draft") i w opublikowanym grafiku ("published") innych okresów firmy.
  `POST /versions/{id}/check` zwraca je w `clashes` (tekst, lokal, `can_remove`, `reason`) z `problems_if_removed` i
  `ok_if_removed`; ekran pyta "Na pewno chcesz to zmienić?" (przeciąganie i panel zmiany; zablokowana osoba z samą
  kolizją dostaje "Przenieś tutaj"). `PATCH .../assignments` z `remove_clashes: true` w jednej transakcji zdejmuje osobę
  z tamtych zmian (zostają puste) i zapisuje zmianę. Szkic innego lokalu zmienia się zwykłą ręczną zmianą. Opublikowany
  grafik innego lokalu zmienia się w miejscu, jak przy zatwierdzonym oddaniu (`take_off_published`): pusta zmiana także
  w nowszym szkicu tego okresu, wpis w historii przypisań (powód "ręczna"), koniec otwartego oddania tej zmiany,
  powiadomienia `shift_removed` (osoba) i `shift_emptied` (kierownicy tamtego lokalu poza tym, kto zmienia). Nie wolno
  zdjąć osoby ze zmiany lokalu, którego kierownik nie prowadzi (właściciel prowadzi wszystkie), ani z opublikowanej
  zmiany, która już się zaczęła: wtedy `can_remove = false` z powodem, a zapis jest odrzucany.
  Razem z "Wpisz mimo to" (PR #44): sama kolizja nie daje się wymusić (`force` jej nie obejmuje), tylko zdjąć. Gdy po
  zdjęciu zostają problemy, które kierownik może pominąć ("nie mogę", zasada "bez wyjątków"), `check` zwraca
  `can_force_if_removed`, a ekran pyta raz i wysyła razem `remove_clashes` i `force`. Odpowiedź dla całego
  przeciągania (`GET .../shifts/{id}/drops`, PR #41) czyta zmiany innych lokali raz i szuka kolizji tylko dla
  upuszczeń, które dają komuś dwie zmiany naraz, więc podgląd od razu mówi "Upuść, a zapytamy, czy ją stamtąd zdjąć".
- Usuwanie (PR #40) przy kilku lokalach: `DELETE /employees/{id}?location_id=` (domyślnie lokal główny). Gdy osoba
  pracuje też w innym lokalu, `removal.leave_location` zdejmuje tylko ten lokal, jej stanowiska tam i polecenia
  kierownika o niej w tym lokalu; usunięcie z lokalu głównego robi lokalem głównym jeden z dodatkowych (pierwszy
  alfabetycznie). Usunięcie z jedynego lokalu działa jak wcześniej (sekcja 25). `EmployeeOut.other_location_names`
  podaje pozostałe lokale osoby, więc pytanie przed usunięciem mówi, gdzie osoba zostanie.
- Między różnymi firmami nic się nie łączy: to osobni pracodawcy i ich dane są rozdzielone.
- Założenia: lokal ułożony pierwszy "ma pierwszeństwo" do osoby (kolejność układania decyduje, jak w Kadromierzu).
- Do sprawdzenia w pilotażu (uwagi Prelinta do #45): czy kierownicy akceptują, że szkic jednego lokalu zabiera osobę
  z puli drugiego (czy lokal główny ma mieć pierwszeństwo); czy pracownik rozumie, że jeden kalendarz i jedno „Gotowe”
  służą wszystkim jego lokalom (dziś „Gotowe” obejmuje okresy innych lokali mieszczące się w tych samych dniach, nie
  odwrotnie); czy kierownicy potrzebują jednodniowego pożyczenia osoby spoza listy bez zaproszenia; czy lista
  niespełnionych próśb ma pokazywać, z którego lokalu jest prośba miesięczna.


## 28. Zwijane miejsca (20.11.2026)

Prośby Piotra z 20.11.2026: "niech »Niespełnione prośby« i »Jak grafik trzyma się zasad« będzie zwijane też" oraz
"jak coś jest zwijane, to niech będzie jakiś znacznik, i najechanie na to niech daje jakiś efekt".

1. Każde zwijane miejsce w aplikacji to `components/ui/disclosure.tsx` (`Disclosure`): strzałka przed napisem, która
   obraca się w dół po rozwinięciu, i jasnoniebieskie tło pod kursorem (jak przy przyciskach "quiet"). `boxed` rysuje
   ramkę (cała sekcja ekranu); bez niej zwijany napis stoi w tekście. Zwijane miejsca w zwijanych miejscach mają
   własne strzałki. `Section collapsible` korzysta z niego i ma `status`: kilka słów na końcu nagłówka, żeby kierownik
   bez rozwijania wiedział, czy warto zajrzeć. Nowe zwijane miejsca używają `Disclosure`, nie gołego `<details>`.
2. Karta "Grafik": "Jak grafik trzyma się zasad" i "Niespełnione prośby" są zwinięte na start. Przy zasadach status
   "N złamanych" i "N spełnionych częściowo" (kolor "woli nie"; częściowo = procent poniżej 100 bez policzonego
   złamania, np. cel godzin 95 %), a gdy nic takiego nie ma: "wszystkie spełnione" tylko wtedy, gdy każda zasada ma
   100 %, inaczej "żadna nie jest złamana" (zasady z "nic do oceny" nie są spełnione). Przy prośbach "N próśb" (kolor)
   i "N do Twojej oceny" dla próśb, których nie umiemy sprawdzić (są w środku, pod "Do Twojej oceny"); "wszystkie
   spełnione" tylko wtedy, gdy nie ma ani jednych, ani drugich. Po uwadze Prelinta (#51) liczba niespełnionych próśb
   stoi w kolorze w statusie, nie w nawiasie w tytule. Liczba pochodzi z API (`VersionOut.unmet_request_count`, przed
   ucięciem listy do 30 próśb pracowników); polecenia kierownika są na liście zawsze w całości. Tak samo liczy zdanie
   nad wynikami (`verdict`), które też nie nazywa zasady spełnionej częściowo "spełnioną" (uwagi Codexa do #51).
   Do sprawdzenia w pilotażu: czy kierownicy otwierają zasady przed publikacją; jeśli nie, zasady mogą startować
   otwarte, gdy coś jest złamane (dziś prawie każdy grafik ma jakąś złamaną zasadę miękką, więc byłyby otwarte zawsze). Wiersz zasady rozwija się tylko wtedy, gdy ma przykłady
   złamań (wtedy ma strzałkę). Polecenia kierownika, których nie udało się spełnić, zostają widoczne nad zwiniętymi
   sekcjami. Zdanie "Chcesz coś zmienić…" pod nimi usunięto 22.11.2026 (zakładka "Zasady" jest obok).
3. "Mój grafik" pracownika (prośba Piotra z 22.11.2026: "Weź zmianę" zajmowało za dużo miejsca): "Zmiany do wzięcia"
   to `Section collapsible`, zwinięta na start, na tym samym miejscu nad najbliższą zmianą. Status: liczba zmian
   ("2 zmiany") i, gdy osoba zgłosiła się do którejś, "czeka na kierownika: N". Napis "Zmiana jest Twoja." po
   przejęciu bez zatwierdzania stoi nad sekcją, poza zwijanym miejscem. Gdy nie ma nic do wzięcia, sekcji nie ma.

## 29. Lepsze rozumienie próśb i robocik, który czyta (20.11.2026)

Po teście Piotra z 20.11: prośba Natalii „Nie stawiajcie mnie z Zuzanną na zamknięciu, obie jesteśmy nowe na kasie”
była opisana jako ogólne „nie chce pracować z Zuzanną”, a prośby Romana „Mogę brać nocki, ale nie więcej niż trzy
w tygodniu” asystent nie umiał zapisać.

- `unikaj_osoby` i `preferuj_osobe` (prośby i polecenia kierownika) mają opcjonalne `shift_type`: liczą się wtedy tylko
  zmiany tego rodzaju (`Request.counts_slot`), w walidatorze i w solverze. Opis: „Natalia i Zuzanna: nie razem na
  zmianie „Popołudniowa””. Kontekst asystenta dopisuje „zamyka lokal” przy zmianach z `is_closing`, więc „zamknięcie”
  wskazuje właściwą zmianę.
- Nowy typ `limit_zmian` (`RequestType.SHIFTS_LIMIT`): `max_shifts` (0–93), opcjonalne `shift_type` i `hours_period`
  (`day` / `week` / `period`, te same okna co `limit_godzin`: `Request.windows`). W oknie liczą się zmiany tej osoby
  w tym lokalu i, bez `shift_type`, jej zmiany w innych lokalach (`Request.shift_windows`). Stopień złamania w oknie:
  przy limicie 0 – 1, gdy jest jakakolwiek zmiana; w pozostałych przypadkach `min(1, nadwyżka / limit)`; wynik
  to średnia okien. Solver: kara za nadwyżkę w każdym oknie, w tej samej skali.
- W schemacie odpowiedzi `hours_period` jest wymagane i nie przyjmuje null (dla innych typów `period`), żeby liczba
  parametrów typu „albo” została w limicie API (test z #48).
- Dane testowe (`seed_test_data`): Natalia ma „nie razem na zmianie „Popołudniowa””, Roman „najwyżej 3 zmiany
  „Nocna” w każdym tygodniu”.
- Gdy asystent czyta wiadomość (prośba `new`, polecenie w kolejce), czat pokazuje małego robota z książką
  (`ReadingRobot` w `components/assistant/Chat.tsx`, własny rysunek SVG): oczy przesuwają się wzdłuż wiersza, głowa
  lekko kiwa (animacja CSS w `tokens.css`, bez emoji; przy `prefers-reduced-motion` stoi w miejscu).
  Obok robota zawsze jest „Myślę…” (Piotr, 22.11.2026; wcześniej „Przygotowuję odpowiedź…”, „Czytamy Twoją
  wiadomość…” i „Wysyłam wiadomość…”), w okienku „Twoje prośby” „Asystent myśli…”.

## 30. Asystent przez OpenRouter (21.11.2026)

Decyzja Piotra (spec.md, „Asystent przez OpenRouter”): skończył się limit Claude API, asystent ma działać przez
OpenRouter z DeepSeek V4.1 Flash. Identyfikator sprawdzony 21.11.2026 w `GET https://openrouter.ai/api/v1/models`:
`deepseek/deepseek-v4.1-flash` (obok jest migawka `deepseek/deepseek-v4.1-flash-1017`).

- Zależność: pakiet `openai` (oficjalny klient API zgodnego z OpenAI chat completions, którego używa OpenRouter;
  te same biblioteki pod spodem co `anthropic`, czyli jeden nowy pakiet), adres `https://openrouter.ai/api/v1`.
- `llm.backend()`: `openrouter`, gdy jest `OPENROUTER_API_KEY`, inaczej `anthropic`, gdy jest `ANTHROPIC_API_KEY`,
  inaczej asystent jest wyłączony (`is_enabled()`). Prompty, narzędzia (`tools.Toolbox`), modele odpowiedzi Pydantic,
  pamięć wiadomości (`context.py`) i sprawdzanie odpowiedzi w `services.py` są wspólne; różni się tylko pętla rozmowy
  (`_converse_openrouter`, `_converse_anthropic`).
- Odpowiedź strukturalna na OpenRouter to wywołanie narzędzia `final_answer`, którego parametry to schemat modelu
  odpowiedzi (`answer_schema`: z `model_json_schema()`, odwołania wstawione, każdy obiekt zamknięty i z wszystkimi polami
  wymaganymi). Nowe pole w `EmployeeReply` / `CommandPlan` trafia więc do modelu bez zmian w `llm.py`. Każda runda
  ma `tool_choice=required` (odczyt albo odpowiedź), po 6 rundach już tylko `final_answer`. `response_format` z
  `json_schema` obok narzędzi nie działa: dostawcy wymuszają wtedy JSON w każdej rundzie i model nie może wywołać
  narzędzia (sprawdzone na żywo 21.11.2026: DeepSeek zaplanował odczyt `my_schedule`, a oddał pustą odpowiedź).
- Argumenty narzędzi nie są wymuszane schematem, więc odpowiedź sprawdza Pydantic: błąd wraca do modelu jako wynik
  narzędzia („Błąd: odpowiedź nie pasuje do schematu (…)”) i model poprawia się w następnej rundzie; null w miejscu
  listy znaczy pustą listę. Dostawca, który zignoruje `tool_choice` i odpisze tekstem, dostaje prośbę o
  `final_answer` (JSON w tekście też jest przyjmowany).
- Rozumowanie modelu (`reasoning_details`) wraca do niego razem z wynikami narzędzi, jak każe OpenRouter dla modeli
  myślących. Głębokość myślenia: `OPENROUTER_EFFORT` → `reasoning.effort` (`none`, `minimal`, `low`, `medium`,
  `high`, `xhigh`; domyślnie `low`, pusta wartość = domyślny poziom modelu).
- Dostawcy: `provider.require_parameters=true` (tylko ci, którzy obsługują wszystkie wysłane parametry, w tym
  narzędzia) i `provider.data_collection=deny` (bez zapisywania i uczenia się na zapytaniach).
- Log workera, jedna linia na odpowiedź: czas, liczba wywołań, narzędzia, tokeny wyjścia, poziom myślenia, model,
  dostawcy i koszt w dolarach z `usage.cost`, np. `assistant EmployeeReply: 2.1 s, 2 calls, tools my_schedule,
  242 output tokens, effort low, deepseek/deepseek-v4.1-flash via Alibaba,InferenceNet, $0.00084`.
- Błędy: brak środków na koncie OpenRouter (402), limit (429), błąd dostawcy w odpowiedzi 200, ucięta odpowiedź
  (`finish_reason=length`) dają `AssistantError`, czyli tę samą ścieżkę co dotąd (prośba do kierownika, polecenie
  „asystent nie dał rady”, ślad w `assistant_misses`).
- Próba na żywo 21.11.2026 na danych `seed_demo` (klucz Piotra tylko w zmiennej środowiskowej, nigdzie nie zapisany):
  pytania pracownika i kierownika z odczytami API, prośby (`wolne_dni` z `cannot`, `limit_zmian` z `shift_type`,
  `unikaj_osoby`), polecenie z niejednoznacznym imieniem (asystent dopytał) i wiadomość niezwiązana z pracą. Odpowiedzi
  przychodziły po 1–5 s (raz 10 s, z jedną poprawką odpowiedzi), koszt ok. 0,0005–0,003 USD za wiadomość.
- Powtórka całego testu Piotra z 20.11 (52 wiadomości) na `seed_test_data`, po uwagach Prelinta do #55: wynik w
  projekcie, `testy-asystenta/deepseek-powtorka-2026-11-21.md`. Zachowanie jak u Claude, dane zgodne z bazą (sprawdzone
  godziny, zmiany i prośby), mediana 4,8 s, najdłużej 34 s przy 6 rundach odczytów. Gdy OpenRouter zawiedzie, nie ma
  automatycznego przejścia na Claude (spec.md).
- Testy: `tests/test_assistant_openrouter.py` na sztucznym transporcie HTTP klienta `openai` (bez sieci i bez klucza).
  `tests/conftest.py` czyści oba klucze w każdym teście, `with_key` ustawia klucz OpenRouter.

## 31. Nadgodziny i krótsza zmiana (20.11.2026)

Zakres produktu: spec.md, „Nadgodziny i krótsza zmiana”.

- Nowa aplikacja `apps/worktime`. Model `HoursChange` (firma, lokal, okres, `slot_key`, pracownik, `date`, godziny z
  grafiku w chwili zapisu `planned_start_at`/`planned_end_at`, godziny naprawdę `start_at`/`end_at`, `reason`,
  `status` pending/approved/rejected/cancelled/replaced/expired, `by_manager`, `requested_by`, `decided_by`, `decided_at`,
  `source_request` = wiadomość czatu, z której przyszło zgłoszenie). Klucz (okres, `slot_key`, osoba) jest stały
  między wersjami, tak jak w `AssignmentEvent`, więc poprawka grafiku niczego nie kopiuje. Na klucz najwyżej jedno
  zgłoszenie `pending` i jedno `approved` (indeksy częściowe); nowe zatwierdzone godziny zmieniają poprzednie na
  `replaced`.
- Opublikowany grafik się nie zmienia: `Shift.start_at/end_at` to dalej plan, który czytają generator, walidator i
  oceny. Zatwierdzone godziny nakłada `worktime.services.worked_hours(assignments)`: raport godzin (+ kolumny
  `longer`/`shorter` i dwie kolumny CSV), „Mój grafik” (`worked_*` przy zmianie, sumy miesięcy, nowa lista `recent`
  zmian z 14 dni), siatka wersji (`VersionShiftOut.worked`, `hours_report`, `assignment_id`) i „Zmień obsadę”
  (`ManagerShiftOut.worked`, `hours_report`). Schematy: `WorkedOut` (godziny, które się liczą) i `WaitingHoursOut`
  (czekające zgłoszenie; nie `HoursReportOut`, bo tak nazywa się raport godzin). Liczy się tylko zmiana, którą ta osoba ma teraz w opublikowanym grafiku.
- Godziny w API to „HH:MM” w czasie lokalu: początek to najbliższy dzień z tą godziną wokół początku z grafiku
  (−1/0/+1 dzień), koniec to pierwsza taka godzina po początku. Odmowy 400/409 z polskim zdaniem: te same godziny
  co teraz, ponad 24 h, nachodzi na inną opublikowaną zmianę tej osoby (w każdym lokalu firmy, z jej zatwierdzonymi
  godzinami), szkic zamiast grafiku opublikowanego, pracownik: zmiana sprzed ponad 14 dni albo nie jego.
- Endpointy: `POST /me/hours-changes` (`report_my_hours`: assignment_id, start_time, end_time, reason, opcjonalnie
  request_id wiadomości czatu), `POST /hours-changes/{id}/cancel` (`cancel_my_hours_change`),
  `GET /manager/hours-changes?company_id=` (`manager_hours_changes`: czekające we wszystkich moich lokalach i
  rozstrzygnięte z 14 dni, `waiting` do licznika w menu), `POST /hours-changes/{id}/approve` i `/reject`,
  `POST /assignments/{assignment_id}/hours` (`set_shift_hours`: kierownik sam; godziny jak w grafiku wracają do
  planu). Kierownik musi prowadzić lokal zmiany (403), firma tylko do odczytu daje 402, obca firma 404.
- Powiadomienia: `hours_reported` (kierownicy lokalu, link „Godziny”), `hours_approved`, `hours_rejected`,
  `hours_set`, `hours_lost` (pracownik, link „Mój grafik”). Osoba traci opublikowaną zmianę: `editing.publish` woła
  `worktime.services.refresh_after_publish(version)`, a zmiany w miejscu (`marketplace._transfer`: oddanie,
  `manager_reassign`, `manager_swap`; `editing.take_off_published`) wołają `person_left_shift`. Czekające
  zgłoszenie i zatwierdzone godziny dostają status `expired` na stałe (nie wracają ze zmianą, więc nic nie liczy się
  dwa razy), a osoba dostaje `hours_lost` (`approved` w payloadzie). Zatwierdzone godziny, na które nachodzi zmiana
  dana osobie później, też wygasają (`overlap` w payloadzie): po publikacji poprawki i po zmianie w miejscu
  (`person_got_shift`); `marketplace.check_assignment` i `swap_problems` dopisują wtedy wcześniej problem z
  `worktime.hours_conflicts` (kierownik może wymusić).
- Recenzja Piotra (21.11): `SetHoursIn.employee_id` (wymagane; inna osoba na zmianie pod blokadą wiersza = 409);
  przywrócenie planu przechodzi kontrolę kolizji; plan asystenta zapisuje przy każdej zmianie godzin `seen`
  (godziny, które się liczą, i id czekającego zgłoszenia), a `set_hours(..., seen=)` daje 409, gdy coś się zmieniło;
  `resolve` zwraca UTC (limit 24 h liczy prawdziwy czas przy zmianie czasu); sumy (raport, CSV, „Mój grafik”) dodają
  sekundy i zaokrąglają raz (`Worked.seconds`); `/me/schedule` liczy też miesiące z `recent`;
  `GET /locations/{id}/handover-shifts?month=RRRR-MM` (cały miesiąc, `apps.core.months.month_range`) dla wyboru
  miesiąca w „Zmień godziny sam”; „Wychodzę teraz” czyta zegar w chwili kliknięcia, w czasie lokalu (przesunięcie z
  `start_at`); zmiana, która skończyła się przy otwartym ekranie, od razu trafia do „Minionych zmian”.
- „Nadgodziny” to godziny ponad grafik, nie nadgodziny z Kodeksu pracy: zdanie pod tabelą ekranu „Godziny” (tylko
  gdy są kolumny nadgodzin) i kolumna CSV „Nadgodziny (ponad grafik)”.
- Asystent pracownika: `EmployeeReply.hours_changes` (0–3: data, od, do, powód; same napisy, bez typów „albo”;
  pusty początek albo koniec, także null od modelu, znaczy „bez zmian”, czyli godzinę, która liczy się teraz).
  Kontekst ma linię „Teraz: GG:MM (czas lokalu)” do „wychodzę teraz”.
  Serwer znajduje opublikowaną zmianę osoby tego dnia (przy dwóch – tę, która nachodzi na podane godziny) i
  sprawdza ją tak jak endpoint; propozycja trafia do `TextRequest.hours_reports`, a czego nie da się zgłosić,
  dopisuje zdanie do odpowiedzi. `MyRequestOut.hours_reports` ma `sent_status` (stan zgłoszenia utworzonego z tej
  wiadomości); czat pokazuje przycisk „Wyślij kierownikowi”, który woła `POST /me/hours-changes` z `request_id`.
  Wiadomość tylko o godzinach kończy się statusem `answered` i nie jest prośbą do generatora. Narzędzie
  `my_schedule` ma też `recent` i godziny naprawdę.
- Asystent kierownika: `CommandPlan.hours_changes` (osoba, data, od, do, powód) i `hours_decisions` (numer
  zgłoszenia z listy „Zgłoszenia innych godzin czekające na decyzję” w kontekście, approve; `pending_hours` liczy je
  raz na polecenie). `check_plan` sprawdza akcje tak jak endpointy i zapisuje opisy aplikacji („Zatwierdzę
  zgłoszenie: Anna Nowak, pt. 20.11, 06:00–15:00 zamiast 06:00–14:00 (nadgodziny: +1 h)”, „Zmienię godziny: Ewa Nowak, …”, „Przywrócę godziny z grafiku: …”; zawsze pełne imię i nazwisko);
  te same godziny co teraz trafiają do „To już jest ustawione”, błędna część blokuje cały plan. `apply_command`
  wykonuje je przez `worktime.services` (najpierw decyzje, potem zmiany) w tej samej transakcji: gdy coś się
  zmieniło od przygotowania planu, nic się nie zapisuje (409 „… Nic z tego planu się nie zapisało.”). Plan, który
  zmienia tylko godziny, nie wymaga otwartego zestawu ustaleń, więc działa też po publikacji okresu
  (`AssistantCommandOut.has_hours`, `hours_only`). Nowe narzędzie `manager_hours_changes`. Na OpenRouter schematy
  odpowiedzi powstają z modeli (`answer_schema`), na Claude zostają w limicie API (test).
- UI pracownika: „Zgłoś inne godziny” (`features/schedule/HoursSheet.tsx`, rachunek godzin w `hours.ts`), status
  zgłoszenia przy zmianie, zwijana sekcja „Minione zmiany”. UI kierownika: ekran „Godziny” ma „Zgłoszone godziny”
  (Zatwierdź / Odrzuć), kolumnę zmian godzin i „Zmień godziny sam” (`features/manager/WorkedHours.tsx`), licznik
  czekających w menu; karta zmiany opublikowanego grafiku ma „Godziny pracy” z „Zmień godziny”, a siatka ikonę
  zegara przy innych godzinach (szara) i czekającym zgłoszeniu (pomarańczowa). Czat pracownika pokazuje
  przygotowane zgłoszenia (`features/availability/HoursProposals.tsx`) z „Wyślij kierownikowi” i stanem po wysłaniu.
- Założenia: okno 14 dni wstecz dla pracownika (jak „Zmień obsadę”); zgłoszenie przyszłej zmiany jest dozwolone
  (np. wiadomo, że trzeba wyjść wcześniej), ale zmienia tylko liczenie godzin, nie plan; nadgodziny to po prostu
  godziny ponad grafik (bez Kodeksu pracy, jak w sekcji 17).
- Poprawki po teście na produkcji (21.11, `testy-asystenta/nadgodziny-produkcja-2026-11-21.md`): instrukcje modelu
  zabraniają numerów zgłoszeń w odpowiedzi (kierownik ich nie widzi) i słów „godziny nadliczbowe”, podają nazwy
  „zgłoszenie nadgodzin” / „zgłoszenie wcześniejszego wyjścia”, każą pisać kierownikowi w czasie przyszłym przed
  „Zatwierdź zmiany”, a przy osobie bez zmiany tego dnia odsyłają do „Popraw grafik” albo „Zmień obsadę sam”
  („Zmień godziny sam” działa tylko na zmianach z grafiku). Notka `HOURS_NOTE` („zapiszę od razu po
  zatwierdzeniu…”) znika z polecenia, gdy kierownik je zatwierdzi albo odrzuci (`api._notes`).
- Powtórka testu po wdrożeniu (21.11): „Celina wyszła dziś o 12” dostało „To już jest ustawione”, choć godziny
  wróciły do planu poza czatem. Model wziął stan z historii. Nagłówek historii kierownika
  (`context.command_history`) i wspólne zasady mówią teraz, że historia to stan z chwili tamtych wiadomości, a
  kierownik ma zawsze dostać `hours_changes`, gdy podaje godziny: to, czy nic się nie zmienia, ocenia serwer
  (`check_set`, „To już jest ustawione”).

## 32. Mniej napisów (22.11.2026)

Decyzja Piotra: bez stałych podpowiedzi, które powtarzają to, co widać na ekranie. Usunięte: notka "Asystent może się
pomylić…" w obu czatach; w "Grafiku" zdanie przy opublikowanej wersji, instrukcja przeciągania przy szkicu, ramka
"Chcesz coś zmienić…" i "Grafik układasz sam, kiedy chcesz."; w oknie publikowania zdanie o powiadomieniach tylko w
aplikacji; drugie zdania podtytułów "Oddane zmiany" i "Godziny w miesiącu"; "Dalsze dni pokażemy…" w "Moim grafiku";
"Po wpisaniu szóstej cyfry…" przy logowaniu; odsyłacz do powodów w arkuszu zmiany bez kandydatów. W "Zasadach" pod
nagłówkiem zostaje "Im wyżej, tym ważniejsza zasada." i notka o Kodeksie pracy, reszta jest pod przyciskiem "i".

## 33. Usuwanie szkicu grafiku (22.11.2026)

Prośba Piotra: przycisk, którym kierownik usuwa szkic grafiku. Wcześniej szkic znikał tylko z całym okresem
(`DELETE /periods/{id}`, sekcja 25) albo przez ponowne układanie.

- `DELETE /versions/{id}` (`delete_schedule_draft`, logika w `editing.delete_draft`): wersja, którą kierownik ogląda,
  o ile nigdy nie była opublikowana (`published_at` puste); inaczej 409. Bieżący szkic daje 409 także w trakcie
  układania tego okresu, bo wynik i tak zapisałby nowy szkic. Kierownik lokalu, `require_writable`.
- Usuwa tylko tę wersję (poprawka 22.11.2026: wcześniej znikały też starsze nieopublikowane wersje, a Piotr
  odebrał to jako usunięcie wszystkich szkiców). Starsza wersja z historii po prostu znika; bieżący grafik bez zmian. Zmiany i przypisania idą kaskadą; `AssignmentEvent` powstaje dopiero
  przy publikacji, oddania zmian wiszą tylko na opublikowanych wersjach.
- Po usunięciu bieżącego szkicu bieżąca jest znów wersja sprzed niego: nieopublikowana zastąpiona (`superseded`, `published_at` puste) wraca do
  `draft` i da się ją edytować; opublikowana zostaje opublikowana (okres `published`). Wersja sprzed ostatniej
  publikacji nigdy nie wraca, bo najnowsza zostająca jest wtedy opublikowana. Gdy nie zostaje żadna wersja, okres
  wraca do `collecting` (pracownicy znów zmieniają dyspozycje, "Poproś o dyspozycje" działa).
- Ekran: czerwona ikona kosza "Usuń szkic" (sam kosz, opis w `aria-label`/`title`, prośba Piotra) przy każdej nieopublikowanej wersji (przy bieżącym szkicu ukryty w trakcie układania);
  `ConfirmSheet` "Usunąć szkic grafiku?" z jednym zdaniem o skutku (wraca poprzedni szkic, wersja N z datą, z poprawkami i przypięciami / zostaje opublikowany grafik / okres wraca do zbierania dyspozycji / przy starszej wersji: "Wersja N zniknie na dobre z historii. Bieżący grafik zostaje bez zmian.") i zdaniem "Obsada dni i zmiany w grafikach innych lokali zostają." i "Tak, usuń szkic" / "Zostaw".

Założenia: usunięcie szkicu nie cofa tego, co poprawki w nim zrobiły poza nim samym: obsada dnia z "Dodaj
miejsce" / "Usuń miejsce" (to ustawienie lokalu) i zdjęcie osoby z opublikowanego grafiku innego lokalu po
potwierdzonym konflikcie (razem z jej innymi godzinami tamtej zmiany) zostają. Ustalenia asystenta i inne godziny opublikowanych zmian zmieniają się dopiero przy publikacji, więc szkic
niczego w nich nie zużył.

## 34. Asystent pracownika dopytuje (22.11.2026)

Prośba Piotra (spec.md, „Asystent pracownika dopytuje”): zamiast od razu oddawać kierownikowi niepewną prośbę,
asystent dopytuje pracownika (od 22.11.2026 najwyżej trzy razy z rzędu, decyzja Piotra; wcześniej raz).

- `llm.EmployeeReply.question` (jedno pytanie albo null) i `answers_question` (numer czekającego pytania z
  kontekstu, na które odpowiada ta wiadomość, albo null). Oba mają wartości domyślne, więc działają tak samo na OpenRouter (argumenty `final_answer`) i na
  Claude (`output_config.format`).
- `TextRequest.question`: pytanie przy wiadomości, która ma status `answered` (nic z niej nie trafia do generatora,
  kierownika ani limitu próśb). `TextRequest.answer_to`: wiadomość, na której pytanie odpowiada ta.
- `services.waiting_questions(row)`: czekające pytania to pytania bez odpowiedzi przy wiadomościach tej osoby z tej
  samej rozmowy (okres albo miesiąc), które asystent pamięta (`context.MAX_CONVERSATION` = 10). Kontekst dostaje je
  z numerami, wiadomością i pytaniem (`context.open_questions`); `conversation` pokazuje też pytania z historii.
  Numer spoza listy znaczy „nowa wiadomość”.
- `_checked_reply`: pytanie modelu (albo pytanie aplikacji o imię kilku osób, `_namesake_question`) daje `answered`
  z pytaniem i bez interpretacji, nawet gdy model podał też preferencje. Odpowiedź (`answers_question` przy otwartym
  pytaniu) dostaje `answer_to` i przechodzi zwykłe sprawdzenie. Odpowiedź może dostać kolejne pytanie (znów
  `answered` z pytaniem i `answer_to`): `services.exchange(row)` idzie po `answer_to` i daje wiadomości z pytaniami
  tej prośby, a `MAX_QUESTIONS = 3` ogranicza je do trzech z rzędu. Czwarte pytanie zamiast odczytu daje
  `needs_manager` / `unsure` z powodem „za dużo pytań” (wcześniej „drugie pytanie” już przy drugim).
  `context.open_questions` podaje przy czekającym pytaniu wcześniejsze wiadomości i pytania (`earlier`) oraz
  `questions_in_a_row`. API: `MyRequestOut.exchange` i `ManagerRequestOut.exchange` (wszystkie wcześniejsze
  wiadomości z pytaniami, od najstarszej; `asked` zostaje = ostatnia z nich). Karta kierownika: „Wcześniej: …”, potem
  „Potem: …” przy kolejnych. `assistant_misses` łączy całą wymianę.
- Pytania aplikacji (dopisane 22.11.2026, gdy wiadomość nie odpowiada na pytanie): `_unknown_name_question` przy
  `unikaj_osoby` / `preferuj_osobe` bez osoby albo z osobą spoza listy (podobne imiona = te same dwie pierwsze
  litery, najwyżej 4) i przy zmianie spoza listy (lista zmian lokalu); `CONFIRM_QUESTION` („Czy dobrze rozumiem:
  <opis>? …”), gdy któraś preferencja ma pewność poniżej `ASSISTANT_MIN_CONFIDENCE` (`_checked_preference` zwraca
  wtedy dane i powód). `assistant_answer.why` mówi, czemu aplikacja zapytała („osoba lub zmiana”, „pewność 0.40”).
  W odpowiedzi na pytanie pyta tak samo, dopóki pytań z rzędu jest mniej niż `MAX_QUESTIONS`. Wyjątek:
  `services.confirmed(answered, text)` = odpowiedź na „Czy dobrze rozumiem…” to samo „tak” (słowa z `YES_WORDS`, w tym
  któreś z `YES_STARTERS`); wtedy `_checked_preferences(sure=True)` pomija wątpliwość i zapisuje odczyt.
- API: `MyRequestOut.question` (tylko przy `answered`), `ManagerRequestOut.asked` (`text`, `question` wiadomości,
  na którą odpowiada prośba). Nowa treść prośby („Popraw”) czyści pytanie. `assistant_misses` pokazuje odpowiedź
  razem z pierwszą wiadomością i pytaniem.
- Czat pracownika: pytanie pogrubione pod odpowiedzią, etykieta „Asystent dopytuje”, pod najnowszym „Odpowiedz niżej.
  Do tego czasu niczego nie zapisuję.”, pole pisania „Odpowiedz asystentowi…”. `MyRequestOut.waiting` (pytanie bez
  odpowiedzi) i `can_answer` (po niej mniej niż 10 wiadomości tej rozmowy): okienko „Twoje prośby” wypisuje takie
  wiadomości osobno („Nie jest zapisana. Asystent pyta: …”) z „Odpowiedz” przy `can_answer`, inaczej „Napisz ją od
  nowa”, i „Niech przeczyta kierownik”. Karta prośby u kierownika: „Wcześniej: „…” Asystent
  zapytał: „…””.

Założenia: pytanie czeka, dopóki asystent je pamięta (10 wiadomości; decyzja Piotra z 22.11.2026, wcześniej tylko
na następną wiadomość). Potem pierwsza wiadomość zostaje niezapisana, ale „Twoje prośby” pokazują ją jako czekającą
(można ją napisać od nowa albo przekazać kierownikowi). Zgłoszenia innych godzin z
wiadomości z pytaniem pokazują się jak dotąd, bo i tak wysyła je dopiero pracownik.

## 35. Wypłata przy godzinach (22.11.2026)

Prośby Piotra (spec.md, „Oczekiwana wypłata”): przy godzinach pracownik widzi wypłatę, a kierownik sumy do wypłaty;
stawka zmienia się „od dnia”; stawka zależy od stanowiska, pory dnia i doświadczenia na stanowisku; bez słowa
„szacunek”, bo to dokładne wyliczenie.

Research (22.11.2026, strony pomocy):
- Kadromierz: domyślna stawka godzinowa stanowiska i indywidualna stawka pracownika na stanowisku („jeśli … pracownicy
  … posiadają np. inny staż pracy”); historia stawek w kontraktach z datą rozpoczęcia, poprzedni kontrakt kończy się
  sam. Strony o stanowiskach, profilu i kontraktach nie opisują dodatków za porę dnia.
- 7shifts: stawka na rolę u pracownika, zmiana z datą obowiązywania (z góry albo do 30 dni wstecz); rozliczone wypłaty
  się nie zmieniają. Deputy: rekordy płacy z datą początku, koszt liczony według dnia zmiany, awans za staż to nowy
  rekord od dnia (ręcznie); reguła za godziny poza zwykłymi liczy tylko część zmiany w oknie. Planday: dodatki w kwocie
  albo procencie za porę dnia, dni tygodnia i święta, z okresem obowiązywania, dla grup pracowników; dodatek za staż
  jako kwota miesięczna. Sling: stawka stanowiska, indywidualna stawka osoby na stanowisku wygrywa.
- Wniosek: stawki od dnia na stanowisku i na osobie na stanowisku (jak Kadromierz), dodatki za porę dnia i dni
  tygodnia w złotych albo procentach, z datami (jak Planday i Deputy), staż przez własną stawkę od dnia (nikt z nich
  nie podnosi stawki sam; stopień doświadczenia w Grafikomacie nie ma daty, więc nie zmienia stawki).

Model: aplikacja `apps/pay` (migracja `pay.0001`; staffing bez pól stawek).
- `PositionRate` (stanowisko, `valid_from`, `hourly_rate`) i `PersonalRate` (osoba, stanowisko, `valid_from`,
  `hourly_rate`): kroki stawki. `valid_from` = null to „od początku” (pierwsza stawka), jeden krok na dzień
  (`nulls_distinct=False`). Krok bez kwoty znaczy od tego dnia „bez stawki” (stanowisko) albo „stawka stanowiska”
  (osoba). Stawka zmiany: ostatni krok osoby na stanowisku zmiany z `valid_from` ≤ `Shift.date`, gdy ma kwotę, inaczej
  ostatni taki krok stanowiska, inaczej brak.
- `PaySupplement` (lokal, nazwa, `start_time`–`end_time`: koniec ≤ początek = przez północ, równe = cała doba,
  `weekdays` jako maska bitów 0 = poniedziałek, `kind` `amount` zł/h albo `percent` stawki zmiany, `value`,
  `positions` puste = wszystkie, `valid_from`/`valid_until` null = bez granicy). Dodatek liczy sekundy części zmiany
  (z `worked_hours`) w oknach dnia w strefie lokalu; dzień tygodnia to dzień początku okna, ważność według dnia zmiany.
  Dodatki się sumują i dotyczą tylko godzin ze stawką.
- Liczenie: `apps/pay/services.py`: `PayRules(assignments)` czyta stawki i dodatki raz (potrzebuje
  `shift__location`), `rate(assignment)` i `supplement(assignment, start_at, end_at, rate)`; `Pay` dodaje kwoty w `Decimal` i zaokrągla
  do grosza raz na końcu (ROUND_HALF_UP), osobno sumę i „w tym dodatki”. Godziny bez stawki idą osobno
  (`unpriced_hours`), nigdy jako 0 zł. Suma raportu to suma zaokrąglonych kwot osób.
- API (tylko kierownik lokalu; zapis także `require_writable`): `GET /locations/{id}/pay-settings` (stanowiska z
  krokami i dodatki), `POST /positions/{id}/rates` i `DELETE /position-rates/{id}`, `GET /locations/{id}/personal-rates`,
  `POST /employees/{id}/rates` (stanowisko osoby w tym lokalu, inaczej 400) i `DELETE /personal-rates/{id}`,
  `POST /locations/{id}/supplements`, `PATCH /supplements/{id}` (zmiana kwoty, godzin, dni albo stanowisk od dnia
  `change_from`: dodatek do dnia przed zostaje, od tego dnia jest nowy; sama nazwa zmienia się w miejscu) i
  `DELETE /supplements/{id}?end_from=` (kończy dodatek dzień wcześniej; dodatek zaczęty od tego dnia albo później
  znika). Zapis kroku z tym samym dniem go zastępuje. Kwoty to liczby (złote), stawka spoza 0,01–10 000 zł, dodatek
  spoza 0,01–10 000 zł albo 1–1000% daje 400 z polskim zdaniem. `MonthHoursOut`, `EmployeeHoursOut` i `HoursReportOut`
  mają `pay`, `supplements_pay` i `unpriced_hours`; CSV ma „Wypłata brutto, zł”, „W tym dodatki, zł” i „Godziny bez
  stawki” przed „Uwagi”. `pay` = null, gdy żadna godzina nie miała stawki.
- Własne stawki nie znikają, gdy osoba traci stanowisko albo odchodzi: dawne zmiany liczą się dalej. Stanowisko
  usunięte całkiem (bez zmian w grafikach) zabiera kroki kaskadą.
- UI: ustawienia lokalu, sekcja „Stawki i dodatki”: przy każdym stanowisku stawka dziś i zaplanowana zmiana, „Zmień
  stawkę” z polem „Od dnia” (domyślnie dziś; pierwsza stawka stanowiska bez daty, własna stawka osoby zawsze z datą),
  lista kroków w zwijanej części z „Usuń” (krok sprzed bieżącego miesiąca pyta najpierw, a dzień w minionym miesiącu
  pokazuje „To zmieni wypłatę za minione miesiące.”, też przy dodatkach); dodatki z formularzem (nazwa, od–do albo cała
  doba, dni, zł/h albo %, stanowiska) i „Zakończ od dnia”. Formularz pracownika: zwijane „Stawki” z tym samym edytorem
  kroków dla każdego zaznaczonego stanowiska. „Mój grafik”: „Wypłata brutto” i „w tym dodatki” w ramce miesiąca.
  „Godziny”: kolumna „Wypłata brutto”, suma w stopce, w trwającym miesiącu zdanie, że kwota obejmuje zmiany, które
  dopiero będą, a przy osobie z innymi lokalami „bez innych lokali” pod kwotą. Kwoty `lib/money.ts` (`Intl.NumberFormat`
  pl-PL, PLN).
- Asystent: ~~`tools.DROPPED_KEYS` usuwa z wyników narzędzi kwoty (uwaga Prelint z 22.11.2026)~~. Od 23.11.2026
  (Piotr: asystent ma liczyć zarobki, RODO później) kwoty trafiają do modelu, sekcja 40.
- Dane przykładowe (`seed_demo`) mają stawki stanowisk i dodatek nocny w piekarniach; firmy testowe
  (`seed_test_data`) nie, żeby było widać stan bez stawek.

Założenia: kwota jest brutto, bez podatku, składek i premii (aplikacja nie zna umowy, sekcja 17), bo stawkę za godzinę
zwykle podaje się brutto. Pracownik widzi wypłatę za cały miesiąc z opublikowanych zmian, także przyszłych, bo o to
chodzi w „oczekiwanej” wypłacie. Dodatku za święto nie ma, bo aplikacja nie zna kalendarza świąt. Każdy kierownik
lokalu widzi i ustawia stawki tego lokalu.
Do sprawdzenia w pilotażu (uwagi Prelinta do #66): czy pracownicy czytają kwotę za cały miesiąc jako pewną wypłatę,
choć część zmian jest jeszcze przed nimi; czy właściciele chcą, żeby stawki widział tylko właściciel, a nie każdy
kierownik lokalu (jeśli odpowiedzi będą różne, najpierw przełącznik w lokalu); czy kierownicy chcą zamknąć minione
miesiące zamiast samego ostrzeżenia; czy zmiana stopnia doświadczenia ma proponować nową stawkę; czy dodatek za święto
jest potrzebny od razu.

## 36. Inny grafik na prośbę kierownika (22.11.2026)

Prośba Piotra (spec.md, „Inny grafik na prośbę kierownika”): gdy ułożony grafik nie pasuje kierownikowi, da się
ułożyć nowy, wyraźnie inny, także według jego prośby w czacie. Wcześniej „Ułóż od nowa” przy tych samych ustawieniach
dawało prawie ten sam grafik (kara stabilności liczy się tylko względem opublikowanej wersji).

- Silnik: `solve(..., diversity_from=[...], min_difference=...)` nie dodaje już twardego ograniczenia w całym modelu.
  Dla każdego wcześniejszego grafiku `_Builder._diversity` liczy, ile jego osobozmian nowy grafik zatrzymuje ponad
  dozwolone `(1 − min_difference)` (zmienna `shortfall`). `solve` ma wtedy fazę między dziurami a karą: przy
  `holes ≤ best` minimalizuje sumę `shortfall` (najwyżej `DIFFERENCE_SHARE` = 20 % limitu czasu, z podpowiedzią z
  fazy 1), potem utrwala ją ograniczeniem i minimalizuje karę jak zawsze. Nigdy więcej dziur i nigdy sprzeczność.
  Osobozmiana = osoba na zmianie danego dnia i stanowiska, bez numeru miejsca (`_shift_of`), więc zamiana dwóch osób
  miejscami nie jest różnicą. Nie liczą się miejsca przypięte, minione dni ani osoba przypięta na innym miejscu tej
  samej zmiany (`_compared`). `changed_shifts(problem, previous, schedule)` zwraca (zmienione, porównane) tą samą
  miarą.
- `GenerationRun.different` (migracja 0011). `POST /periods/generate` przyjmuje `different: true`;
  `GenerationRunOut.different`. `run_generation` przy `different` czyta wszystkie wersje okresu (najnowsze
  `COMPARED_VERSIONS` = 100, jednym zapytaniem, `_earlier_versions`), woła solver z `min_difference=DIFFERENT_SHARE`
  (0,3) i dopisuje do `scores.notes` nowego szkicu zdanie z `_difference_notes`: różnica względem najnowszej, potem
  „Od starszych wersji też różni się co najmniej co trzecią zmianą.” albo wersja, od której różni się najmniej; gdy
  próg nie został osiągnięty, także „Bardziej się nie dało…”; gdy `manager_rules` albo `employee_requests` wyszły
  niżej niż w najnowszej wersji, „Słabiej niż w wersji N: …”.
- Powrót do starszego szkicu: `editing.restore_version(version, user)` kopiuje wersję (zmiany, osoby, przypięcia,
  ręczne poprawki, uwagi) jako nowy szkic o kolejnym numerze z `ScheduleVersion.restored_from` = numer źródła
  (migracja 0012), poprzedni szkic staje się historią, ocena liczy się od nowa. 409, gdy wersja była opublikowana,
  jest najnowsza, powstała przed ostatnią publikacją albo okres się układa. `POST /versions/{id}/restore`
  (`restore_version`, 201 `VersionSummaryOut`); `VersionOut.restorable`, `VersionSummaryOut.restored_from`. Ekran:
  „Wróć do tej wersji” przy starszej wersji, lista „Wersje” pisze „jak wersja 5”. Wspólne kopiowanie z
  `start_draft` w `_copy_version`.
- Ekran „Grafik”: `ArrangeButton different` („Ułóż inaczej”, ikona Shuffle) obok „Ułóż od nowa”, gdy okres ma
  wersję. Arkusz „Ułożyć inny grafik?” mówi o co trzeciej zmianie, ostrzega o ręcznych poprawkach jak zwykle, mówi o
  koszu i ma „Napisz asystentowi, co ma być inaczej” (`openChat` z okresem i tekstem „Ułóż inny grafik, żeby ”).
- Asystent: `llm.CommandPlan.arrange` (`no` / `again` / `different`, domyślnie `no`), opis w `COMMAND_SYSTEM`
  (punkt 4) i w przewodniku kierownika. `services._checked_arrange` w `check_plan`: tylko okres ustaleń, który ma
  wersję, lokal nie w archiwum, bez trwającego układania; inaczej uwaga i cały plan zablokowany. Plan dostaje
  `arrange = {period_id, different}`, ostatni punkt „Po zatwierdzeniu ułożę nowy grafik na okres …, wyraźnie inny
  niż obecny.” / „… ułożę grafik na okres … od nowa.” i uwagę o przypięciach, ręcznych poprawkach i koszu.
  `has_changes` liczy `arranges(plan)`. `apply_command` po ustaleniach i godzinach woła `_apply_arrange` →
  `request_generation` w tej samej transakcji; błąd (trwające układanie 409, okres opublikowany) cofa
  cały plan z dopiskiem „Nic z tego planu się nie zapisało.”. `AssistantCommand.generation_run` (migracja assistant
  0004); `AssistantCommandOut.arranges`, `changes_agreements`, `run_id`. Czat po zatwierdzeniu pokazuje
  `RunProgress` (postęp, „Anuluj”, „Zobacz szkic”).

Piotr (22.11.2026): 30 % zostaje; „Ułóż inaczej” ma dawać ciągle nowe grafiki (kierownik klika do skutku), więc
porównanie obejmuje wszystkie wersje zamiast trzech, a wszystkie szkice zostają i da się do nich wrócić.
Założenia: asystent nie układa
pierwszego grafiku okresu (to dalej przycisk z ostrzeżeniami o terminie i brakujących dyspozycjach). Okres
opublikowany zamyka ustalenia, więc z czatu da się układać tylko przed publikacją; przycisk „Ułóż inaczej” działa
też przy poprawkach opublikowanego grafiku (tak jak „Ułóż od nowa”), a odmowa czatu go wskazuje
(`ARRANGE_PUBLISHED`), arkusz nie pokazuje wtedy „Napisz asystentowi”. Linia planu nie podaje numeru wersji, bo do
zatwierdzenia mogła powstać nowsza; numer podaje uwaga w nowym szkicu.

Limit ułożeń (Piotr, 22.11.2026: „Bez limitu ułożeń”): najpierw domyślnie wyłączony, tego samego dnia usunięty
z kodu (sekcja 39).

## 37. Prośby na stałe (22.11.2026)

Prośba Piotra (spec.md, „Prośby na stałe”): prośba pracownika może obowiązywać we wszystkich kolejnych okresach.

- `TextRequest.lasting`: prośba liczy się w swoim okresie (miesiącu) i w każdym okresie, który zaczyna się
  później, w lokalach, w których osoba pracuje. `TextRequest.ends_from`: pierwszy dzień okresu (miesiąca), od którego
  zakończona prośba się nie liczy; okres się liczy, gdy jego początek jest wcześniej. `ended_by`: kto zakończył
  (pracownik albo kierownik). `ends_from` tylko przy `lasting` (ograniczenie w bazie).
- `TextRequest.lasting_from(day)`: prośby na stałe (zrozumiane albo zostawione kierownikowi) napisane na okres lub
  miesiąc zaczynający się najpóźniej `day` i niezakończone przed nim; `ended=True` daje zakończone dokładnie od `day`
  (zostają na liście tego okresu jako zakończone). `for_periods` dokłada je dla osób, które pracują w lokalu okresu.
  `is_own(periods | month)` odróżnia prośbę napisaną na ten okres od przeniesionej z wcześniejszego.
- Generator (`problem_builder.requests`): prośba na stałe ma `location=None` (dotyczy osoby, jak prośba na miesiąc).
  W przeniesionej liczą się tylko części z `lasting` (każda część interpretacji ma ten klucz; konkretne daty nigdy
  nie są na stałe, a dni spoza okresu i tak odpadają).
- Asystent: `llm.Preference.lasting` (domyślnie false, więc działa tak samo przez OpenRouter i Claude); prompt mówi,
  że życzenie ogólne bez dat jest na stałe, a z datami, „w tym miesiącu” albo z chwilowym powodem tylko na ten okres;
  przy „na razie” bez końca asystent pyta. `_checked_preference` zapisuje `lasting` przy części (false przy datach),
  wiadomość jest na stałe, gdy którakolwiek część jest. `context.prior_requests` dokłada prośby na stałe
  z wcześniejszych miesięcy, a `request_history` oznacza je `from_earlier_month`; korekta takiej prośby
  (`replaces_request`) nie zastępuje jej, tylko kończy od okresu nowej wiadomości (`ends_from`, `ended_by` =
  pracownik) i łączy przez `supersedes`. Nowa treść czytana od nowa ustawia `lasting` z odczytu; odpowiedź
  i odrzucenie nie są na stałe.
- API pracownika: `MyRequestOut.lasting`, `can_last` (zapisana i nie tylko o konkretnych dniach), `carried_from`
  (pierwszy dzień okresu/miesiąca, na który ją napisano, gdy jest z wcześniejszego), `ends_from`, `ended_by`
  (`employee`/`manager`), `ended` (zakończona dokładnie od okresu na ekranie). `GET /me/requests` dla okresu albo
  miesiąca zwraca też przeniesione i zakończone tam prośby. `PATCH /me/requests/{id}` z `lasting` (tylko w otwartym
  okresie prośby, 409 przy samych datach) zaczyna od nowa: czyści zakończenie. `POST /me/requests/{id}/end`
  (`company_id`, `period_id` albo `month`, `ended`): okres musi zbierać dyspozycje, a miesiąc nie może minąć;
  „Przywróć” tylko własne zakończenie dokładnie od tego okresu.
- API kierownika: `ManagerRequestOut.lasting`, `carried_from`, `ended`, `ended_by`; lista okresu ma też prośby
  zakończone od niego. `POST /periods/{id}/requests/{rid}/end` (`ended`): tylko prośba na stałe z wcześniejszego
  okresu; zakończenie wysyła pracownikowi powiadomienie `request_ended`, a przywrócić można tylko zakończenie
  kierownika.
- Ekrany: w „Twoich prośbach” pod zapisaną prośbą przyciski „Tylko w grudniu” (albo dni okresu) i „Na stałe”
  (też pod odczytem w czacie, który mówi „także w kolejnych miesiącach”); przeniesione prośby w osobnej liście:
  „Na stałe od grudnia.” z „Zakończ” → „Zakończyć od stycznia?” → „Tak, zakończ”; zakończone: „Zakończona: nie
  obowiązuje od stycznia.” z „Przywróć” albo „Zakończył ją kierownik.”. Czat miesiąca nie pokazuje przeniesionych
  próśb. Karta prośby u kierownika: znacznik „Na stałe” / „Na stałe od grudnia”, „Zakończ od tego okresu” obok
  „Odrzuć prośbę”; zakończona: przerywana ramka, „Zakończona”, kto zakończył i „Przywróć prośbę”.

Założenia: domyślnie na stałe jest każda prośba bez dat, bo pracownik rzadko dopisuje „zawsze”, a wybór widać
i zmienia się jednym stuknięciem. Kierownik nie może zakończyć prośby w okresie, na który ją napisano (tam ją
odrzuca); odrzucenie i ważność są wspólne dla wszystkich okresów prośby. Zakończenie zawsze od początku okresu
(miesiąca) na ekranie. Prośby napisane przed zmianą zostają tylko na swój okres.

## 38. Koszty asystenta (22.11.2026)

Prośba Piotra (spec.md, „Koszty asystenta”): ile kosztuje OpenRouter na konto i na lokal, a u kierownika osobno
rozmowy z asystentem i układanie grafiku.

- Model językowy wołają tylko `llm.read_request` (wiadomość pracownika, `TextRequest`) i `llm.plan_command` (wiadomość
  kierownika, `AssistantCommand`). Generator (`apps/scheduling/generation.py`, CP-SAT) nie woła żadnego API, więc jego
  „koszt” to liczba uruchomień i czas solvera z `GenerationRun` (`time_ms`, `requested_by`, lokal albo grupa).
- `llm.Usage`: backend, model, dostawcy, liczba zapytań (rund), tokeny wejścia i wyjścia, koszt w USD (`Decimal`;
  na OpenRouter suma `usage.cost` z każdej rundy, przy Claude `None`, bo API nie podaje ceny), czas i `failed`.
  `_converse` zbiera ją dla jednej odpowiedzi i dodaje do tej, którą podał `with llm.tracking(usage)` (zmienna
  kontekstu), także gdy odpowiedź kończy się `AssistantError`: rundy przed błędem też kosztowały. Linia w logu
  workera zostaje bez zmian.
- `AssistantUsage` (migracja assistant 0005, firma jak każdy model firmy): `kind` (`employee`/`manager`), `location`
  i `user` (`SET_NULL`, żeby koszt został po usunięciu), `message_id` (id `TextRequest` albo `AssistantCommand` bez
  klucza obcego, z tego samego powodu), `backend`, `model`, `providers`, `calls`, `input_tokens`, `output_tokens`,
  `cost_usd` (null = bez ceny), `failed`, `duration_ms`, `created_at`. Zapis tylko wtedy, gdy przyszła choć jedna
  odpowiedź API (bez niej nic nie kosztowało; testy z podmienionym `llm.read_request` nie dodają zapisów).
- `services.interpret_request` i `services.run_command` obejmują wywołanie modelu `llm.tracking` i zapisują koszt
  (`costs.record`) przed zapisem wyniku, więc także gdy wiadomość w międzyczasie zmieniono („skipped”). Błąd zapisu
  kosztu tylko trafia do logu i nie psuje odpowiedzi. Lokal wiadomości pracownika to `TextRequest.location` (lokal
  okresu albo główny lokal osoby), kierownika `AssistantCommand.location`.
- `apps/assistant/costs.py`: `summary(month, by)` z `by` = `company`, `location` albo `person` (osoba w firmie, czyli
  użytkownik). Kolumny: wiadomości pracownika i ich koszt, wiadomości kierownika i ich koszt, razem, nieudane, bez
  ceny, tokeny, liczba układań i minuty solvera. Miesiąc liczy się w czasie polskim (`TIME_ZONE`) po `created_at`.
  Układanie grupy lokali liczy się raz w firmie i u osoby, w każdym lokalu grupy (lokale okresów uruchomienia), a jego
  czas dzieli się po równo między te lokale. Liczą się uruchomienia, które wystartowały (`started_at`).
- Admin Django: lista „Koszty asystenta” tylko do odczytu (filtry: rodzaj, nieudane, backend, firma, data) i strona
  „Zestawienie miesiąca” (`admin:assistant_assistantusage_summary`, wybór miesiąca, trzy tabele: firmy, lokale,
  osoby, i pobranie CSV każdej). `manage.py assistant_costs --month 2026-11 --by person` daje ten sam CSV.
- Nic z tego nie trafia do API aplikacji ani do narzędzi asystenta: koszty widzi tylko superadmin.

Założenia: „konto” to osoba z loginem w danej firmie (sumę firmy daje `--by company`). Koszt w dolarach, bo tak liczy
OpenRouter; przeliczenie na złote zostaje Piotrowi. Czas solvera nie jest przeliczany na pieniądze, bo serwer kosztuje
tyle samo bez względu na liczbę układań.

## 39. Bez limitu ułożeń (22.11.2026)

Prośba Piotra: „w ogóle usuń ten limit na tworzenie grafików” (po napisie „Ułożenia grafiku w tym miesiącu: 4. Bez
limitu.” na ekranie „Dostęp”).

- Usunięte: ustawienie `GENERATION_MONTHLY_LIMIT` (`settings.py`, `docker-compose.yml`, `.env.example`,
  `.env.production.example`), sprawdzanie w `request_generation` (429) i oddawanie użycia przy błędzie i anulowaniu,
  model `GenerationUsage` z adminem (migracja billing 0003 usuwa tabelę), `generations_used` i `generations_limit`
  w `SubscriptionOut`, napis na ekranie „Dostęp” i linia „Zostało ułożeń…” w arkuszu układania (arkusz nie czyta już
  `useSubscription`), 429 z `generate_schedule` i `apply_assistant_command`.
- Blokada na wierszu firmy w `request_generation` zostaje: dzięki niej dwa równoczesne zlecenia tego samego okresu
  nie przejdą obok sprawdzenia „już się układa” (409).
- Zestawienie kosztów (sekcja 38) liczy układania z `GenerationRun`, więc się nie zmienia.

Założenia: tabela `GenerationUsage` miała tylko liczniki ułożeń; ta sama informacja (z czasem solvera) jest w
`GenerationRun`, więc usuwamy ją razem z danymi. Linia `GENERATION_MONTHLY_LIMIT=0` w `.env` serwera po wdrożeniu nic
nie robi i można ją skasować.

## 40. Uwagi z testu pracownika na telefonie (23.11.2026)

Spec: „Uwagi z testu pracownika na telefonie”.

- Grafik w przygotowaniu: `MyScheduleOut.preparing` (lokal, od, do) to okresy moich lokali w statusie `draft`
  (ułożone, nigdy nieopublikowane) w zasięgu „Mojego grafiku”; `MyCalendarOut.unpublished` to dni z `locked` w takich
  okresach (bez dni z moją opublikowaną zmianą). „Mój grafik” pokazuje zdanie pod „Grafik jest opublikowany do…”,
  „Kiedy mogę” rozróżnia dni układane od opublikowanych. Blokada dni się nie zmienia.
- Czat pracownika: bez stopki „Czyta to…” przy włączonym asystencie; „O prośbach i Twoich danych” mówi, że kierownik
  widzi zapisane prośby i to, co pracownik mu przekaże, a nie całą rozmowę.
- Kwoty dla asystenta: `tools.DROPPED_KEYS` ma już tylko telefony i pola ekranów. `MyShiftOut.hourly_rate`
  (stawka osoby w dniu zmiany) i `MyShiftOut.pay` (brutto za zmianę z dodatkami) liczy `PayRules` jak miesiąc; ekran
  ich nie pokazuje. Nowe narzędzia kierownika: `pay_settings` i `personal_rates` (istniejące GET, uprawnienia
  kierownika lokalu); `hours_report` oddaje już `pay`.
- Prośba o stanowisko: typ `stanowisko` w `readings` (`positions` = id stanowiska o tej nazwie wśród stanowisk osoby,
  po jednym na lokal, `position_name`, `avoid`), w odpowiedzi modelu `position` i `avoid_position` (zwykłe pola
  z wartością domyślną, bo schemat odpowiedzi ma limit 16 pól z unią). W silniku `RequestType.POSITION` z
  `Request.positions`: walidator liczy odsetek zmian osoby w dniach prośby na złym stanowisku (jak `shift_type`),
  solver daje karę za każdą taką zmianę. Kontekst pracownika ma „Twoje stanowiska” (nazwy bez powtórzeń). Aplikacja
  sama pyta: o które stanowisko (nieznane przy kilku) albo, przy jednym stanowisku i „nie na nim”, czy chodzi
  o wolne; „tylko na nim” przy jednym stanowisku nic nie zapisuje i mówi to; stanowisko spoza stanowisk osoby idzie
  do kierownika z jasnym zdaniem. Polecenie kierownika sprawdza, czy osoba ma to stanowisko w lokalu (także przy
  zatwierdzeniu i kopiowaniu ustaleń, `agreements.positions_held`).
- Święta: `apps/core/holidays.py` liczy dni ustawowo wolne w Polsce na dowolny rok (Wielkanoc algorytmem, Wigilia od
  2025). Linia z nimi jest w kontekście pracownika (lata dzisiaj i okresu wiadomości) i kierownika (lata dzisiaj,
  za trzy miesiące i okresów lokalu). Zasada tematów w `COMMON_RULES`: `app` dla wszystkiego, co dotyczy pracy i jej
  organizacji, także świąt i podstaw prawa pracy (krótko, jako informacja ogólna), `unrelated` tylko dla spraw wyraźnie
  niezwiązanych; w razie wątpliwości `app`. Stała odmowa wymienia też wypłaty, święta i zasady pracy.

Założenia: pracownik widzi przez asystenta swoją stawkę za godzinę (to jego własna stawka, wynika też z wypłaty za
miesiąc). Ekran „Mój grafik” jej nie pokazuje, żeby nie dokładać napisów. Stanu danych na serwerze nie sprawdzono
(bez logowania na konto); przyczynę z grudniem odtworzono z kodu: tylko szkic okresu daje taki obraz.
