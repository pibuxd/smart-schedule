# Grafikomat

Aplikacja do układania grafików pracy dla lokali zmianowych: piekarni, kawiarni, restauracji i hoteli.
Pracownik zaznacza w telefonie, kiedy może pracować, a menedżer jednym kliknięciem dostaje gotowy grafik dla wszystkich lokali.

Stan: prototyp w budowie (etap 1 z 10: szkielet aplikacji).

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
(konto tworzy się komendą `docker compose exec api python manage.py createsuperuser`).

## Uproszczenia prototypu

Lista będzie uzupełniana w kolejnych etapach.

- Wszystko działa lokalnie; wdrożenie na serwer VPS to późniejszy krok (ten sam `docker-compose.yml`, inna wartość `SITE_ADDRESS`).
