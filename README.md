# Grafikomat

Aplikacja do układania grafików pracy dla lokali zmianowych: piekarni, kawiarni, restauracji i hoteli.
Pracownik zaznacza w telefonie, kiedy może pracować, a kierownik jednym kliknięciem dostaje gotowy grafik lokalu,
który może poprawić i opublikować.

Stan: prototyp, wszystkie 10 etapów planu zbudowane.

- Wymagania: [docs/spec.md](docs/spec.md)
- Plan techniczny, model danych, endpointy i założenia każdego etapu: [docs/plan.md](docs/plan.md)
- Komendy i konwencje dla programistów: [CLAUDE.md](CLAUDE.md)
- Wdrożenie na serwer VPS: [docs/deploy.md](docs/deploy.md)

## Co jest w prototypie

- Pracownik (telefon): logowanie kodem SMS, zaproszenie do lokalu, „Kiedy mogę” (kalendarz z pędzlem: nie mogę /
  chętnie, godziny dnia, powtarzanie co tydzień, kopiowanie z poprzedniego miesiąca), prośby pisane słowami,
  „Mój grafik”, oddawanie i branie zmian, powiadomienia w aplikacji.
- Kierownik (komputer): lokale i grupy, stanowiska, zmiany, obsada z wyjątkami, pracownicy i zaproszenia,
  przegląd dyspozycji i próśb, zasady w kolejności ważności z podglądem skutku, układanie grafiku jednym
  przyciskiem, ocena w trzech liczbach, wyjaśnienia, ręczne poprawki z walidacją na żywo, publikacja z wersjami,
  zatwierdzanie oddanych zmian, godziny w miesiącu z eksportem CSV, kody dostępu i okres próbny.
- Generator: OR-Tools CP-SAT w osobnym workerze (najpierw jak najmniej zmian bez obsady, potem zasady kierownika
  i prośby pracowników w proporcji 80 do 20), niezależny walidator, który ma ostatnie słowo.
- Asystent (Claude): czyta prośby pracowników i polecenia kierownika pisane zwykłymi słowami i zamienia je na
  ustawienia z zamkniętych list. Grafiku nie układa. Kierownik widzi plan zmian i sam go zatwierdza.

## Uruchomienie lokalne

Potrzebny jest Docker z Docker Compose.

```bash
cp .env.example .env          # ustaw DJANGO_SECRET_KEY na długi losowy tekst
docker compose up --build
```

Potem otwórz http://localhost:8080.

Dane przykładowe (sieć 4 piekarni pod Krakowem i osobna kawiarnia do sprawdzania izolacji firm):

```bash
docker compose exec api python manage.py seed_demo            # raz
docker compose exec api python manage.py seed_demo --reset    # usuń i utwórz od nowa
```

Komenda wypisuje numery telefonów kierownika i przykładowego pracownika.

Logowanie: wpisz numer telefonu na stronie logowania. Kod nie przychodzi SMS-em, tylko trafia do logu serwera:

```bash
docker compose logs api | grep "SMS to"
```

Żeby zobaczyć cały obieg na danych przykładowych: zaloguj się jako kierownik, wejdź w lokal, w karcie „Grafik”
naciśnij „Ułóż grafik”, popraw, co chcesz, i opublikuj. Pracownik zobaczy wtedy swoje zmiany w „Mój grafik”.
Szybciej z konsoli: `docker compose exec api python manage.py generate_schedule --company 6a1e0000-0000-4000-8000-000000000001`.

Panel administratora Django: http://localhost:8080/api/admin/. Konto tworzy komenda
`docker compose exec api python manage.py createsuperuser` (login to numer telefonu). W panelu superadmin tworzy
kody dostępu (Kody dostępu → Dodaj; kod widać w całości tylko raz) i może zmienić profil wag lokalu lub grupy.
Nowa firma bez kodu ma 30 dni okresu próbnego, potem działa tylko do odczytu, dopóki kierownik nie wpisze kodu.

Opis API: http://localhost:8080/api/docs.

### Asystent (Claude)

Asystent działa, gdy w `.env` jest klucz:

```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-5-5     # tańszy wariant do krótkich próśb: claude-haiku-5-5
```

Po zmianie `.env` uruchom ponownie `docker compose up`. Klucz czytają tylko kontenery `api` i `worker`; nie trafia
do przeglądarki ani do repozytorium.

Bez klucza aplikacja działa w całości, tylko bez asystenta: prośby pracowników trafiają do kierownika tak, jak
zostały napisane (generator ich nie liczy), a zasady kierownik ustawia ręcznie na liście.

Z kluczem:

- Pracownik pisze prośbę w „Kiedy mogę” → „Coś jeszcze?”. Po kilku sekundach widzi pod nią „Tak to
  zrozumieliśmy: …” i może nacisnąć „Nie o to mi chodziło”. Zrozumiane prośby generator bierze pod uwagę; niepewne
  czyta sam kierownik.
- Kierownik w karcie „Zasady” lokalu pisze polecenie, np. „Ania i Kasia nie na jednej zmianie” albo „równe
  weekendy są ważniejsze niż cel godzin”. Dostaje plan prostymi zdaniami i skutek na ostatnim grafiku. Dopiero
  „Zatwierdź zmiany” cokolwiek zmienia. Potem układa grafik od nowa.

Do Claude wysyłana jest tylko treść prośby lub polecenia, daty okresu, nazwy zmian, stanowisk i zasad oraz imiona
osób z jednego lokalu (bez nazwisk, numerów telefonów i grafiku).

### Bez Dockera (dla programistów)

Backend, worker i frontend osobno: komendy są w [CLAUDE.md](CLAUDE.md), sekcja „Commands”. Testy backendu nie
potrzebują klucza do Claude (używają atrapy).

## Jak aplikacja nie pozwala, żeby „wszystko było bardzo ważne”

- Kierownik nie wybiera poziomów ważności. Ważność to miejsce na liście zasad i na liście poleceń o osobach, a
  każda pozycja ma inne miejsce. Podniesienie jednej rzeczy zawsze obniża pozostałe. Asystent też nie może nadać
  poziomu: musi wskazać miejsce i napisać, co przez to spadnie niżej.
- „Bez wyjątków” to osobny, świadomy wybór. Asystent ustawia je tylko na wyraźne „nigdy”, plan pokazuje skutek
  na ostatnim grafiku, a od trzeciej takiej zasady aplikacja ostrzega, że mogą zostać zmiany bez obsady.
- Prośby pracownika: poziom wynika z powodu, nie z wykrzykników, a wszystkie prośby jednej osoby w okresie
  dzielą jeden budżet wagi. Pięć próśb „bardzo ważnych” waży razem tyle, co jedna bardzo ważna i jedna ważna.

## Uproszczenia prototypu

Logowanie i dostęp

- SMS-y z kodem logowania nie są wysyłane: kod jest w logu serwera. Bramka SMS to osobna klasa (`SMS_BACKEND`)
  do podłączenia przy wdrożeniu. Tylko numery +48.
- Bez płatności online: dostęp dają kody z panelu administratora i 30-dniowy okres próbny.
- Poza kodem logowania nic nie idzie SMS-em ani e-mailem; powiadomienia są tylko w aplikacji, bez powiadomień push.

Dane i bezpieczeństwo

- Izolacja firm jest w warstwie aplikacji (filtr po firmie i testy), bez Row Level Security w Postgresie.
- Wdrożenie to jeden serwer VPS z Dockerem, bez zapasowego serwera; kopie bazy leżą na tym samym serwerze (zob. [docs/deploy.md](docs/deploy.md)).
- Zmianę numeru telefonu pracownika robi superadmin w panelu.

Grafik i generator

- Aplikacja nie zna typu umowy i nie sprawdza Kodeksu pracy. Limity czasu pracy to zwykłe zasady, które kierownik
  włącza i może oznaczyć „bez wyjątków”; za zgodność grafiku z prawem odpowiada kierownik.
- Generator daje jeden wariant grafiku (kod jest przygotowany pod trzy) i ma limit 30 sekund na lokal.
- Każdy lokal jest układany osobno. Generator przypisuje ludzi tylko do ich lokalu domowego; praca w innym lokalu
  to ręczna poprawka kierownika albo wzięcie oddanej zmiany.
- Grafik powstaje tylko na polecenie kierownika, nigdy sam ani okresowo. Ponowne układanie usuwa nieprzypięte
  ręczne poprawki.
- Wynik układania odświeża się przez odpytywanie co 1–2 sekundy, bez websocketów.
- Nie ma zamian zmian między dwiema osobami (jest oddawanie i branie zmian z akceptacją kierownika), urlopów ani
  rejestracji czasu pracy.
- Stopień doświadczenia pracownika ustawia kierownik ręcznie; nie jest liczony z przepracowanych godzin.

Asystent

- Jedna prośba pracownika to jedna sprawa. Tekst z kilkoma życzeniami naraz czyta kierownik.
- Asystent kierownika działa w lokalu. Zasady wspólne dla grupy lokali ustawia się ręcznie, a powiązania lokali
  poleceniem („ułóż te dwa lokale razem”) jeszcze nie ma.
- Polecenia o konkretnych osobach są miękkie: generator stara się je spełnić, ale nie zostawi przez nie zmiany
  bez obsady. „Bez wyjątków” mają tylko zasady z listy.
- Polecenia o osobach mają własną kolejność, osobną od listy zasad.
- Asystent nie prowadzi rozmowy: każde polecenie jest czytane osobno, razem z aktualną listą zasad i poleceń.
- Nie mierzymy jeszcze trafności interpretacji na prawdziwych prośbach; próg pewności (0,6) i limity (200 poleceń
  na firmę w miesiącu, 10 próśb na osobę w okresie) są ustawione na oko i do zmiany w `.env`.
