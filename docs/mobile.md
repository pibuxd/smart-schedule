# Aplikacje iOS i Android

Aplikacje to ten sam frontend React/Vite spakowany w aplikacji przez Capacitor 8. Łączą się z API Django przez
HTTPS. Strona WWW działa bez zmian. Zakres opisuje [spec.md](spec.md) („Aplikacje na iPhone'a i Androida”),
a technikę [plan.md](plan.md) (sekcja 46). Ten plik mówi, jak zbudować aplikacje, podpisać je, przetestować
i opublikować.

**Wysłanie wersji do sklepów to decyzja Piotra.** Nic w repozytorium nie wysyła niczego do App Store Connect ani do
Google Play.

## Co gdzie jest

| Miejsce | Co |
|---|---|
| `frontend/capacitor.config.ts` | identyfikator `pl.grafikomat.app`, nazwa, katalog z frontendem (`dist`) |
| `frontend/ios/` | projekt Xcode (Swift Package Manager, bez CocoaPods), `App.entitlements`, `PrivacyInfo.xcprivacy` |
| `frontend/android/` | projekt Gradle, `GrafikomatPlugin.java` (kod z SMS-a, sprawdzenie Firebase), podpisywanie w `app/build.gradle` |
| `frontend/src/native/` | sesja w aplikacji, push, kod SMS, zapis pliku CSV |
| `frontend/scripts/` | `app-icons.mjs` (ikony i ekrany startowe), `app-version.mjs` (numer wersji) |
| `backend/apps/core/native.py` | sesja w nagłówku zamiast ciasteczka, CORS tylko dla aplikacji |
| `backend/apps/notifications/push.py` | rejestracja telefonów, wysyłka przez APNs i FCM |

## Sekrety (nigdy w repozytorium)

| Sekret | Gdzie trzymać |
|---|---|
| Klucz APNs `AuthKey_XXXX.p8` | serwer: `./secrets/` obok `docker-compose.yml` (git-ignored) i menedżer haseł |
| Plik konta usługi Firebase (JSON) | serwer: `./secrets/` i menedżer haseł |
| `google-services.json` (Firebase, Android) | `frontend/android/app/google-services.json` tylko na komputerze, który buduje (git-ignored) |
| Klucz przesyłania Androida (`.jks`) i hasła | menedżer haseł + `frontend/android/keystore.properties` (git-ignored) albo zmienne środowiska |
| Certyfikaty i profile Apple | pęk kluczy Maca (Xcode zarządza nimi sam) |
| Adres serwera dla aplikacji | `frontend/.env.native.local` (git-ignored) |

`.gitignore` w `frontend/android` i `frontend/ios` blokuje `*.jks`, `*.keystore`, `keystore.properties`,
`google-services.json`, `*.p8`, `*.p12`, `*.mobileprovision`. Klucza przesyłania Androida nie da się odtworzyć:
zrób kopię w dwóch miejscach (Play App Signing pozwala go wymienić, ale tylko przez zgłoszenie do Google).

## Budowanie

Wymagania: Node 22 i `npm install` w `frontend`. Android: JDK 21 i Android SDK 36 (Android Studio albo
`cmdline-tools`). iOS: Mac z Xcode 16 lub nowszym.

```bash
cd frontend
cp .env.native.example .env.native.local   # raz; wpisz adres serwera, np. VITE_API_ORIGIN=https://grafikomat.pl
npm run build:native                       # frontend w trybie aplikacji + kopiowanie do ios/ i android/
npx cap open android                       # Android Studio, albo bez niego:
cd android && ./gradlew assembleDebug      # app/build/outputs/apk/debug/app-debug.apk
npx cap open ios                           # Xcode (tylko na Macu)
```

Budowanie w trybie `native` przerywa się, gdy `VITE_API_ORIGIN` nie jest adresem `https://`. Aplikacja wysyła
zapytania na ten adres; serwer musi znać jej origin (`NATIVE_APP_ORIGINS`, domyślnie `capacitor://localhost` i
`https://localhost`, czyli nic nie trzeba ustawiać).

Po każdej zmianie frontendu, która ma trafić do aplikacji: `npm run build:native` i nowa wersja w sklepie. Aplikacja
nie pobiera frontendu z serwera, więc zmiana w API musi być zgodna wstecz z wersją zainstalowaną na telefonach.

Ikony i ekrany startowe powstają ze znaku z `Wordmark.tsx`: `npm run app:icons` (potrzebuje globalnie
zainstalowanego Playwrighta). Wynik jest w repozytorium.

## Numer wersji

```bash
npm run app:version -- 1.0.1 2    # wersja widoczna w sklepie, numer kompilacji
```

Skrypt zmienia `android/gradle.properties` (`versionName`, `versionCode`) i projekt Xcode (`MARKETING_VERSION`,
`CURRENT_PROJECT_VERSION`). Numer kompilacji musi rosnąć przy każdym wysłaniu do TestFlight albo Google Play.

## Powiadomienia push

Bez kluczy aplikacja działa, tylko bez pushy (powiadomienia są w aplikacji jak dotąd).

### Apple (APNs)

1. developer.apple.com → Certificates, Identifiers & Profiles → Identifiers: identyfikator `pl.grafikomat.app`
   z usługą **Push Notifications** (Xcode zrobi to sam przy pierwszym podpisaniu, potem zaznacz usługę).
2. Keys → „+” → **Apple Push Notifications service (APNs)** → pobierz `AuthKey_XXXX.p8` (tylko raz). Zapisz Key ID
   i Team ID (Membership).
3. Na serwerze: plik do `./secrets/`, w `.env`:
   ```
   PUSH_APNS_KEY_FILE=/run/secrets/grafikomat/AuthKey_XXXX.p8
   PUSH_APNS_KEY_ID=XXXX
   PUSH_APNS_TEAM_ID=YYYY
   ```
   potem `deploy/update.sh`. Jeden klucz działa dla wersji z Xcode (sandbox) i z TestFlight/App Store (produkcja);
   serwer sam próbuje drugiego środowiska, gdy Apple odrzuci token.
4. W Xcode: target App → Signing & Capabilities → sprawdź, że jest **Push Notifications** (uprawnienie jest już
   w `App.entitlements`). Tryb w tle nie jest potrzebny.

### Google (Firebase Cloud Messaging)

1. console.firebase.google.com → nowy projekt → dodaj aplikację Android `pl.grafikomat.app`.
2. Pobierz `google-services.json` do `frontend/android/app/` (tylko na komputerze, który buduje). Bez tego pliku
   aplikacja Android działa, ale nie prosi o zgodę na powiadomienia i nie rejestruje telefonu.
3. Project settings → Service accounts → **Generate new private key**: plik JSON do `./secrets/` na serwerze,
   w `.env` `PUSH_FCM_CREDENTIALS_FILE=/run/secrets/grafikomat/firebase.json`, potem `deploy/update.sh`.

Push wysyła kontener `worker` (kolejka `default`). Log: `docker compose logs worker | grep push`.

## Podpisywanie

### Android

```bash
keytool -genkeypair -v -keystore grafikomat-upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000
```

`frontend/android/keystore.properties` (git-ignored):

```
storeFile=/pełna/ścieżka/grafikomat-upload.jks
storePassword=…
keyAlias=upload
keyPassword=…
```

albo zmienne `GRAFIKOMAT_KEYSTORE_FILE`, `GRAFIKOMAT_KEYSTORE_PASSWORD`, `GRAFIKOMAT_KEY_ALIAS`,
`GRAFIKOMAT_KEY_PASSWORD`. Potem `cd frontend/android && ./gradlew bundleRelease` →
`app/build/outputs/bundle/release/app-release.aab`. Bez tych danych wersja wydania wychodzi niepodpisana.
W Google Play włącz **Play App Signing** (domyślne): Google podpisuje aplikację swoim kluczem, a ten plik jest
tylko kluczem przesyłania.

### iOS

1. Konto Apple Developer Program (99 USD rocznie; dla firmy potrzebny numer D-U-N-S).
2. Xcode → target App → Signing & Capabilities → Team = konto firmy, „Automatically manage signing”.
3. Product → Archive → Distribute App → App Store Connect → Upload (to już wysyłka: robi ją Piotr).

## Testy przed sklepem

### TestFlight (iOS)

1. App Store Connect → Apps → „+” → nowa aplikacja: nazwa „Grafikomat”, język polski, bundle ID
   `pl.grafikomat.app`, SKU dowolne.
2. Wyślij archiwum z Xcode (wyżej). Po kilkunastu minutach kompilacja jest w TestFlight.
3. Testerzy wewnętrzni (do 100 osób z dostępem do App Store Connect) testują od razu. Zewnętrzni (do 10 000, np.
   pracownicy Pszepiekarni przez link publiczny) wymagają krótkiego przeglądu Apple przy pierwszej kompilacji.
4. Pytanie o szyfrowanie: aplikacja ma `ITSAppUsesNonExemptEncryption = NO` (tylko HTTPS), więc App Store Connect
   nie pyta przy każdej kompilacji.

### Google Play

1. play.google.com/console → konto dewelopera (25 USD jednorazowo; konto firmy potrzebuje numeru D-U-N-S).
2. Utwórz aplikację, wyślij `.aab` do **Testy wewnętrzne** (do 100 osób z listy e-mail, dostępne w kilka minut).
3. Konto osobiste założone po listopadzie 2023 musi przed produkcją przejść **test zamknięty: co najmniej 12 osób
   przez 14 dni bez przerwy**. Konto firmowe nie ma tego wymogu.

### Co sprawdzić na prawdziwych telefonach

- Logowanie: na Androidzie systemowe okno „Zezwól na odczyt wiadomości” po SMS-ie i wpisany kod; na iPhonie kod nad
  klawiaturą. Wpisanie ręczne.
- Zamknięcie aplikacji (usunięcie z ostatnich) i ponowne uruchomienie: nadal zalogowany.
- Pytanie o zgodę na powiadomienia po zalogowaniu (Android 13+, iOS).
- Scenariusz: pracownik A oddaje zmianę → pracownik B dostaje push przy zamkniętej aplikacji → dotknięcie otwiera
  „Zmiany do wzięcia” z obrysowaną zmianą → „Weź zmianę” → kierownik dostaje push → dotknięcie otwiera „Oddane
  zmiany” z tą zmianą → „Zatwierdź” → B dostaje push, dotknięcie otwiera tę zmianę w „Mój grafik”.
- „Wyloguj” → kolejne powiadomienia nie przychodzą na ten telefon.
- „Pobierz CSV” w „Godzinach” otwiera „Udostępnij”.
- Wycięcie ekranu (notch), pasek stanu i dolny pasek nawigacji nie zasłaniają przycisków.

## Prywatność

Aplikacja nie śledzi, nie ma reklam ani analityki, nie dzieli się danymi. Wszystko szyfrowane w drodze (HTTPS).

**App Store Connect → App Privacy** (i `PrivacyInfo.xcprivacy`): zbierane, powiązane z osobą, cel „App Functionality”,
bez śledzenia:

| Dane | Skąd |
|---|---|
| Numer telefonu (Contact Info → Phone Number) | logowanie |
| Imię i nazwisko (Contact Info → Name) | konto, zaproszenia |
| Inne dane finansowe (Financial Info → Other) | numer konta do wypłaty, stawki i wypłaty |
| Inne treści użytkownika (User Content → Other) | dyspozycje, prośby i wiadomości do asystenta |
| Identyfikator urządzenia (Identifiers → Device ID) | token powiadomień push |

**Google Play → Data safety**: te same dane (Personal info: Name, Phone number; Financial info: Other; Messages:
Other in-app messages; Device or other IDs), zbierane, nieudostępniane, szyfrowane w drodze, cel „App functionality”
i „Account management”. Treść wiadomości do asystenta przetwarza model językowy (OpenRouter albo Anthropic) jako
podmiot przetwarzający, nie trzecia strona w rozumieniu Data safety, ale trzeba to opisać w polityce prywatności.

Treść powiadomień push (godziny i miejsca zmian, imiona) przechodzi przez serwery Apple i Google, bez numeru konta.

Uprawnienia: Android `INTERNET`, `POST_NOTIFICATIONS` (i dodane przez Firebase). Brak dostępu do SMS-ów, kontaktów,
lokalizacji, aparatu. Dane aplikacji nie trafiają do kopii zapasowej Androida (logowanie się nie przenosi).

## Publikacja

1. Karta sklepu: nazwa, krótki i pełny opis po polsku, zrzuty ekranu (iPhone 6,9" i 6,5", Android telefon), ikona
   512 px dla Google Play (`frontend/store/google-play-icon-512.png`), kategoria Business / Biznes, kontakt.
2. Adres polityki prywatności (oba sklepy) i, dla Google Play, adres strony z prośbą o usunięcie konta.
3. Dane logowania dla recenzentów (patrz niżej), kwestionariusz treści (IARC w Google Play), grupa docelowa 18+.
4. iOS: App Store Connect → wybór kompilacji z TestFlight → Submit for Review. Android: z testów do Produkcji
   (najlepiej stopniowo, np. 20%).

## Zanim aplikacje trafią do sklepów (otwarte)

- **Usuwanie konta w aplikacji.** Apple (wytyczna 5.1.1(v)) wymaga, by konto założone w aplikacji dało się w niej
  usunąć; Google Play wymaga strony z prośbą o usunięcie. Grafikomat jeszcze tego nie ma. Trzeba zdecydować, co
  zostaje w historii grafików po usunięciu osoby (dziś usunięcie z lokalu ukrywa osobę, a historia zostaje).
- **Polityka prywatności** pod stałym adresem (oba sklepy jej wymagają).
- **Konto dla recenzentów.** Logowanie jest tylko kodem SMS, a recenzent Apple/Google go nie dostanie. Potrzebny numer
  demonstracyjny ze stałym kodem (wyłącznie dla jednego konta z danymi przykładowymi) albo inny sposób; decyzja
  Piotra.
- **Bramka SMS** zamiast kodu w logu serwera (`SMS_BACKEND`), żeby testerzy z TestFlight i Google Play dostali kody.
  Dla podpowiedzi kodu na Androidzie SMS musi przyjść od nadawcy spoza kontaktów (tak działa każda bramka).
- **Domena serwera**: adres `sslip.io` nadaje się do testów, do sklepu lepiej własna domena (Apple sprawdza, czy
  aplikacja działa w czasie przeglądu).
- **Wytyczna Apple 4.2** (minimalna funkcjonalność): aplikacja na tym samym kodzie co strona może zostać uznana za
  „stronę w ramce”. Atuty: powiadomienia push, podpowiedź kodu, zapis plików, praca na telefonie. Ryzyko zostaje.
