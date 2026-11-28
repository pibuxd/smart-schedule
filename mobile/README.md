# Grafikomat: aplikacja na iPhone'a i Androida (Flutter)

Natywna aplikacja Grafikomatu. Rozmawia z tym samym API Django co strona, przez HTTPS. Zakres: `docs/spec.md`
(„Aplikacje na iPhone'a i Androida”), technika i etapy: `docs/plan.md` (sekcja 49), budowanie i sklepy: `docs/mobile.md`.

```bash
cp config/example.json config/local.json      # raz; wpisz adres serwera w API_ORIGIN
flutter pub get
flutter run --dart-define-from-file=config/local.json
flutter analyze && flutter test
dart run swagger_parser                         # klient API z ../frontend/openapi.json po zmianie API
```

Katalog `web/` służy tylko do podglądu ekranów w przeglądarce (zrzuty ekranu bez telefonu); nie jest publikowany.
