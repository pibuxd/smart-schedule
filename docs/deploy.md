# Wdrożenie na serwer VPS

Cały Grafikomat (baza, API, worker, generator, Caddy z frontendem) działa na jednym serwerze z Dockerem.
Wystarczy mały VPS: 2 rdzenie i 4 GB RAM, Debian 12/13 albo Ubuntu 24.04, z własnym adresem IPv4.

W przykładach `ADRES` to adres IP serwera, a `PORT` to port SSH podany przez dostawcę (zwykle 22).
Haseł i kluczy nie zapisujemy w repozytorium ani w tym pliku.

## 1. Pierwsze uruchomienie

Zaloguj się na serwer i wklej jedno polecenie:

```bash
ssh -p PORT root@ADRES
curl -fsSL https://raw.githubusercontent.com/pibuxd/smart-schedule/main/deploy/setup-server.sh | sh
```

Skrypt `deploy/setup-server.sh`:

1. instaluje Dockera i gita, dodaje 2 GB pamięci wymiany, jeśli serwer jej nie ma,
2. pobiera kod do `/opt/grafikomat`,
3. tworzy `/opt/grafikomat/.env` z `.env.production.example`; `DJANGO_SECRET_KEY` i hasło bazy losuje na serwerze
   i nigdzie ich nie wysyła,
4. buduje i uruchamia kontenery (`docker-compose.yml` + `docker-compose.prod.yml`: porty 80 i 443, baza niewidoczna z zewnątrz),
5. ustawia codzienną kopię bazy o 03:15.

Na końcu wypisuje adres aplikacji. Pierwsze budowanie trwa kilka minut. Skrypt można uruchomić ponownie:
istniejącego `.env` i bazy nie rusza.

### Adres i HTTPS

Logowanie działa tylko przez HTTPS (ciasteczko sesji jest wysyłane wyłącznie szyfrowanym połączeniem).

- Bez własnej domeny skrypt używa darmowej nazwy `<adres-ip-z-myślnikami>.sslip.io`, która wskazuje na adres serwera.
  Caddy sam pobiera dla niej certyfikat. To rozwiązanie na start i na testy: nazwa jest brzydka, a wydanie certyfikatu
  może się czasem opóźnić, bo z tej samej usługi korzysta wiele osób.
- Z własną domeną: ustaw u rejestratora rekord `A` domeny na adres serwera, poczekaj, aż zacznie działać
  (`ping twoja-domena.pl` pokazuje adres serwera), i podaj ją skryptowi:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/pibuxd/smart-schedule/main/deploy/setup-server.sh | sh -s -- twoja-domena.pl
  ```

  Jeśli aplikacja już działa pod nazwą sslip.io, zmień w `/opt/grafikomat/.env` trzy wartości
  (`SITE_ADDRESS`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`) i uruchom `docker compose up -d`.

## 2. Pierwsze logowanie

Wszystkie polecenia z katalogu `/opt/grafikomat`.

```bash
docker compose exec api python manage.py createsuperuser     # konto do panelu /api/admin/ (login = numer telefonu)
docker compose exec api python manage.py seed_demo           # opcjonalnie: dane przykładowe (4 piekarnie i kawiarnia)
```

Bramka SMS nie jest jeszcze podłączona, więc kod logowania nie przychodzi SMS-em, tylko trafia do logu serwera.
Wpisz numer w aplikacji, a potem odczytaj kod:

```bash
docker compose logs api --since 5m | grep "SMS to"
```

Dopóki tak jest, zalogować może się tylko ktoś, komu podasz kod z logu. Przed wpuszczeniem prawdziwych pracowników
trzeba podłączyć bramkę SMS (nowa klasa wskazana w `SMS_BACKEND`).

Kody na darmowy dostęp dla firm tworzy się w panelu administratora: Kody dostępu → Dodaj.

## 3. Aktualizacja

Serwer aktualizuje się sam. Co 5 minut `deploy/auto-update.sh` (cron `/etc/cron.d/grafikomat-auto-update`) sprawdza,
czy na gałęzi `main` w GitHubie jest nowy kod. Jeśli jest, uruchamia `deploy/update.sh`: kopia bazy, pobranie kodu,
przebudowanie kontenerów i ponowne uruchomienie (migracje bazy wykonują się przy starcie API). Nowa wersja działa
zwykle do 10 minut po merge'u, a przerwa w działaniu trwa kilkanaście sekund.

- Co się działo: `tail -n 50 /var/log/grafikomat-update.log`.
- Jeśli wdrożenie wersji się nie uda, automat nie próbuje jej ponownie, tylko czeka na następny commit (poprawkę).
  Wpis `UPDATE FAILED` w logu znaczy, że trzeba zajrzeć: `cd /opt/grafikomat && docker compose ps`.
- Ręcznie, bez czekania: `/opt/grafikomat/deploy/update.sh`.
- Wyłączenie automatu: `rm /etc/cron.d/grafikomat-auto-update`. Ponowne włączenie: uruchom jeszcze raz polecenie z punktu 1.
- Na serwerze, który powstał przed dodaniem automatu, wystarczy raz uruchomić polecenie z punktu 1 (niczego nie kasuje).

Uwaga: każdy merge do `main` trafia od razu na działający serwis. Przed wpuszczeniem prawdziwych użytkowników
warto wrócić do ręcznego wdrażania albo wdrażać z osobnej gałęzi.

## 4. Kopie zapasowe

- `deploy/backup.sh` zapisuje zrzut bazy do `/var/backups/grafikomat` i usuwa starsze niż 14 dni. Uruchamia go cron
  (`/etc/cron.d/grafikomat-backup`), wynik jest w `/var/log/grafikomat-backup.log`.
- Kopie leżą na tym samym serwerze. Co jakiś czas pobierz najnowszą na swój komputer:
  `scp -P PORT root@ADRES:/var/backups/grafikomat/<plik> .`
- Przywrócenie (zastępuje obecne dane):

  ```bash
  cd /opt/grafikomat
  docker compose stop api worker solver
  docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  gunzip -c /var/backups/grafikomat/<plik>.sql.gz | docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
  docker compose up -d
  ```

## 5. Zabezpieczenie dostępu do serwera

Hasło roota od dostawcy przychodzi mailem, więc zastąp je kluczem SSH.

Na swoim komputerze (klucz prywatny zostaje tylko u Ciebie):

```bash
ssh-keygen -t ed25519            # raz; zatwierdź domyślną ścieżkę i ustaw hasło do klucza
ssh-copy-id -p PORT root@ADRES   # wgrywa klucz publiczny, pyta ostatni raz o hasło roota
ssh -p PORT root@ADRES           # sprawdź, że wchodzisz już bez hasła roota
```

Dopiero gdy logowanie kluczem działa, wyłącz na serwerze logowanie hasłem i zmień hasło roota:

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/00-keys-only.conf
sshd -t && systemctl reload ssh
passwd
```

Nie zamykaj bieżącego połączenia, dopóki w drugim oknie nie sprawdzisz, że nowe logowanie kluczem działa.

## 6. Przydatne polecenia

```bash
cd /opt/grafikomat
docker compose ps                         # czy wszystko działa
docker compose logs -f api                # log API (także kody logowania)
docker compose logs -f caddy              # log serwera WWW (certyfikat HTTPS)
docker compose logs -f solver             # log generatora
docker compose restart api worker solver
```
