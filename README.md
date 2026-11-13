# Grafikomat

Aplikacja do układania grafików pracy dla lokali zmianowych: piekarni, kawiarni, restauracji i hoteli.
Pracownik zaznacza w telefonie, kiedy może pracować, a menedżer jednym kliknięciem dostaje gotowy grafik dla wszystkich lokali.

Stan: prototyp w budowie (etap 2 z 10: modele danych i dane przykładowe).

- Wymagania: [docs/spec.md](docs/spec.md)
- Plan techniczny i etapy: [docs/plan.md](docs/plan.md)
- Komendy i konwencje dla programistów: [CLAUDE.md](CLAUDE.md)
- Wdrożenie na serwer VPS: [docs/deploy.md](docs/deploy.md)

## Uruchomienie lokalne

Potrzebny jest Docker z Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Potem otwórz http://localhost:8080. Panel administratora Django jest pod http://localhost:8080/api/admin/
(konto tworzy się komendą `docker compose exec api python manage.py createsuperuser`, login to numer telefonu).

Dane przykładowe (sieć 4 piekarni pod Krakowem i osobna kawiarnia do sprawdzania izolacji firm):

```bash
docker compose exec api python manage.py seed_demo            # raz
docker compose exec api python manage.py seed_demo --reset    # usuń i utwórz od nowa
```

Logowanie (od etapu 3; ekrany powstaną w etapie 6, na razie jest samo API, opis pod http://localhost:8080/api/docs):
aplikacja prosi o kod na numer telefonu, a kod zamiast SMS-em trafia do logu serwera
(`docker compose logs api | grep "SMS to"`). Numer menedżera danych przykładowych wypisuje `seed_demo`.

Kody na darmowy dostęp tworzy superadmin: panel administratora → Kody dostępu → Dodaj. Kody widać w całości tylko raz,
zaraz po wygenerowaniu. Firma bez aktywnego kodu działa w trybie tylko do odczytu.

Jeśli baza powstała jeszcze na etapie 1, usuń ją raz (`docker compose down -v`), bo od etapu 2 aplikacja ma własny model
użytkownika (logowanie numerem telefonu).

## Uproszczenia prototypu

Lista będzie uzupełniana w kolejnych etapach.

- SMS-y z kodem logowania nie są wysyłane: kod jest wypisywany w logu serwera. Bramka SMS to osobna klasa
  (`SMS_BACKEND`) do podłączenia przy wdrożeniu.
- Bez płatności online: dostęp dają kody generowane w panelu administratora.
- Izolacja firm jest w warstwie aplikacji (filtr po firmie i testy), bez Row Level Security w Postgresie.
- Wdrożenie to jeden serwer VPS z Dockerem, bez zapasowego serwera; kopie bazy leżą na tym samym serwerze (zob. [docs/deploy.md](docs/deploy.md)).
