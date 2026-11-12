# Grafikomat

Aplikacja do układania grafików pracy dla lokali zmianowych: piekarni, kawiarni, restauracji i hoteli.
Pracownik zaznacza w telefonie, kiedy może pracować, a menedżer jednym kliknięciem dostaje gotowy grafik dla wszystkich lokali.

Stan: prototyp w budowie (etap 2 z 10: modele danych i dane przykładowe).

- Wymagania: [docs/spec.md](docs/spec.md)
- Plan techniczny i etapy: [docs/plan.md](docs/plan.md)
- Komendy i konwencje dla programistów: [CLAUDE.md](CLAUDE.md)

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

Jeśli baza powstała jeszcze na etapie 1, usuń ją raz (`docker compose down -v`), bo od etapu 2 aplikacja ma własny model
użytkownika (logowanie numerem telefonu).

## Uproszczenia prototypu

Lista będzie uzupełniana w kolejnych etapach.

- Izolacja firm jest w warstwie aplikacji (filtr po firmie i testy), bez Row Level Security w Postgresie.
- Wszystko działa lokalnie; wdrożenie na serwer VPS to późniejszy krok (ten sam `docker-compose.yml`, inna wartość `SITE_ADDRESS`).
