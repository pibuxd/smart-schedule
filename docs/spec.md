# Grafikomat: specyfikacja prototypu

Źródło prawdy dla zakresu prototypu. Gdy decyzja się zmienia, najpierw poprawiamy ten plik, potem kod.
Plan techniczny (architektura, modele, endpointy, ekrany, etapy): [plan.md](plan.md).
Założenia przyjęte przy planowaniu są w sekcji "Założenia" na końcu planu.

Budujemy działający prototyp webowy aplikacji do układania grafików pracy dla lokali zmianowych (piekarnie, kawiarnie, restauracje, hotele). To własny, oryginalny produkt: nie kopiuj nazwy, wyglądu ani brandingu istniejących aplikacji. Nazwa robocza: "Grafikomat". Produkt będzie sprzedawany wielu firmom; pierwszym testerem jest sieć 4 piekarni pod Krakowem, w której grafik dla wszystkich lokali układa jedna osoba.


## Cel prototypu

Udowodnić, że aplikacja jest wygodna, oszczędza czas i jest łatwa także dla osób starszych i niechętnych technologii (np. piekarzy). Cele mierzalne: pracownik zaznacza dyspozycyjność na tydzień w mniej niż 1 minutę, bez instrukcji; menedżer publikuje grafik dla 4 lokali w mniej niż 15 minut.

## Zasady projektowe

- Klikanie przed pisaniem: wszystko, co da się zaznaczyć palcem lub wybrać z listy, robi się bez pisania i bez LLM. LLM służy tylko do próśb pisanych tekstem, których nie da się zaznaczyć w kalendarzu.
- Nikt nie widzi i nie ustawia liczbowych wag. Interfejs nie używa słów "waga", "solver", "optymalizacja".
- Menedżer nie zna się na optymalizacji. Ważność zasad miękkich ustala kolejnością na jednej liście (przeciąganie), a nie oceną każdej zasady osobno, żeby nie dało się oznaczyć wszystkiego jako najważniejsze.
- Zasady, wagi i prośby należą do lokalu albo grupy lokali, nigdy do całego systemu. Zasada grupy obowiązuje w jej lokalach; lokal może ją u siebie zmienić lub wyłączyć.
- Głos menedżera ma zdecydowanie większe znaczenie niż prośby pracowników.

## Struktura

Firma -> grupa lokali (opcjonalna) -> lokal. Jeden menedżer może prowadzić wiele lokali; jego podstawowym ekranem jest widok zbiorczy grupy. Pracownik jest zasadniczo na stałe w jednym lokalu; praca w innym to wyjątek (wzięcie oddanej zmiany, pożyczenie przez menedżera). Jedno konto na numer telefonu w całym systemie; przynależność do firmy i lokalu wynika z przyjętych zaproszeń. Dane firm są od siebie odizolowane: każdy wiersz ma firmę, a każde zapytanie jest nią ograniczone.

## Pracownik (najpierw telefon)

1. Mój grafik: data, lokal, godziny, stanowisko; kto jest ze mną na zmianie.
2. Dyspozycyjność wyłącznie ręcznie w kalendarzu, bez LLM. W kalendarzu są tylko dwa stany: nie mogę / chętnie; dzień bez zaznaczenia znaczy "mogę" (decyzja Piotra z 13.11.2026: "wolę nie" i "obojętnie" usunięte, takie życzenia pracownik pisze jako prośbę tekstem, np. "wolałbym mieć wolne 5 grudnia", a LLM zamienia ją na typ wolne_dni). Zaznaczanie "pędzlem" (decyzja Piotra z 12.11.2026): pracownik wybiera na dole ekranu stan (nie mogę, chętnie albo gumkę "wyczyść", która zdejmuje zaznaczenie i godziny), który zaznacza, a potem stuka w dzień albo przeciąga po kilku dniach naraz; nie trzeba pamiętać kolejności stanów. Zapis automatyczny, "Cofnij" cofa ostatni ruch. Stuknięcie w dzień, który ma już wybrany stan, albo narzędzie "Godziny dnia" otwiera ten dzień; pod kalendarzem jest lista dni z godzinami z przyciskiem "Zmień". Można tam wybrać godziny (prośba Piotra z 12.11.2026: pracownicy są elastyczni i zaznaczają godziny, w których mogą): przy "chętnie" i na dniu bez zaznaczenia znaczą "mogę tylko w tych godzinach" (zmiana spoza nich tego dnia liczy się jak "nie mogę"), przy "nie mogę" znaczą "nie w tych godzinach"; koniec przed początkiem to godziny do rana następnego dnia (nocka). Opcje: "powtarzaj co tydzień do [data]" (studentom plan zmienia się co semestr) i "skopiuj z poprzedniego miesiąca". Widoczny termin zgłoszenia. Po terminie pracownik nadal może poprawiać dyspozycje, aż kierownik ułoży grafik; dni zmienione po terminie kierownik widzi w siatce ze znakiem "po terminie" (decyzja Piotra z 12.11.2026, zamiast twardego zamknięcia).
3. Prośby tekstem tylko dla spraw spoza kalendarza, np. "nie chcę zmiany z osobą X". Pracownik widzi, jak system zrozumiał prośbę, i może poprawić. Prośby widzi tylko menedżer.
4. Po publikacji pracownik widzi tylko swój grafik na najbliższy okres i sumę godzin. Nie widzi, czy jego prośby zostały spełnione, ani powodów.
5. Oddanie zmiany: "oddaj zmianę" -> powiadomienie w aplikacji dla osób ze wszystkich lokali firmy, które zaznaczyły wtedy dyspozycyjność, mają właściwe stanowisko i nie złamią twardych reguł -> "biorę" -> menedżer zatwierdza. Zapisuj historię przypisań zmiany, żeby później łatwo dodać zamiany zmian między dwiema osobami. Do zatwierdzenia zmiana należy do osoby, która ją oddaje. Po zatwierdzeniu zmiana od razu przechodzi w opublikowanym grafiku (bez nowej wersji: ślad zostaje w historii przypisań, z osobą, która zatwierdziła), jest przypięta, żeby ponowne układanie nie cofnęło uzgodnienia, a wszyscy zainteresowani dostają powiadomienie.
6. Powiadomienia tylko w aplikacji (zakładka "Powiadomienia" z licznikiem nowych): prośba o dyspozycje, nowy lub poprawiony grafik, zmiana do wzięcia, decyzja kierownika o oddanej zmianie. Kierownik widzi chętnych do wzięcia zmian w "Oddane zmiany" z licznikiem w nagłówku.

## Menedżer (najpierw komputer)

1. Dane lokalu w formularzach: stanowiska, typy zmian z godzinami (stałe lub dowolne, także przez północ), obsada według stanowisk dla dnia tygodnia i typu zmiany z wyjątkami na daty, okres grafiku (tydzień lub miesiąc), termin dyspozycji, pracownicy (stanowiska, stopień doświadczenia, osobiste maksimum i cel godzin). Aplikacja niczego z tego nie zakłada z góry.
   Stopień doświadczenia (decyzja Piotra z 13.11.2026): kierownik daje każdej osobie na liście pracowników jedną z trzech etykiet: początkujący, samodzielny (domyślna) albo doświadczony. Pracownik nigdy nie widzi swojego stopnia. Generator używa go w zasadzie "Początkujący z doświadczonymi", żeby na zmianie nie było wielu niedoświadczonych osób naraz. Pomysł na później: podpowiedź stopnia z przepracowanych godzin.
2. Przegląd dyspozycji: siatka pracownicy x dni, lista próśb z interpretacją (menedżer może prośbę odrzucić albo oznaczyć jako ważniejszą lub mniej ważną), lista osób bez zgłoszonej dyspozycji.
3. Zasady lokalu: gotowa lista z przełącznikami i licznikami; kolejność na liście = ważność; każdą zasadę można oznaczyć "bez wyjątków" (twarda). Przed zapisaniem pokaż skutek zmiany na danych z ostatniego okresu, np. "przez tę zasadę 6 próśb nie zostałoby spełnionych".
4. Generowanie grafiku osobno dla każdego lokalu (lokale są od siebie niezależne: każdy ma własne zasady i wagi; "ułóż dla wszystkich" uruchamia osobne generowanie dla każdego lokalu). Lokale zależą od siebie tylko wtedy, gdy kierownik tak powie w poleceniu dla asystenta. Wynik z oceną i wyjaśnieniami; ręczna edycja (przeciąganie, przypinanie) z walidacją na żywo przez endpoint; publikacja z wersjami.
5. Ponowne generowanie układa od nowa wszystko poza zmianami przypiętymi i dniami, które minęły: nieprzypięte ręczne poprawki znikają. Kierownik, który chce coś zmienić w wyniku, pisze polecenie dla asystenta (LLM), a ten zamienia je na zasady i ich ważność.
6. Okres grafiku: kierownik wpisuje daty okresu i dzień, w którym będzie układał grafik. Może jednym przyciskiem poprosić wszystkich pracowników lokalu o dyspozycje (powiadomienie w aplikacji z okresem i terminem). Widzi, kto już wpisał dyspozycje, a kto nie, i może przypomnieć tylko tym, którzy jeszcze nie wpisali.
   Grafik powstaje wyłącznie na świadome polecenie kierownika, gdy minie termin albo gdy wszyscy wpiszą dyspozycje (Piotr, 12.11.2026: ludzie zwlekają do ostatniej chwili, więc grafik ma sens dopiero przy komplecie danych). Aplikacja nie układa grafiku sama, okresowo ani automatycznie; może jedynie podpowiedzieć, że przyszła pora.
7. Podsumowanie godzin w miesiącu z podziałem na lokale, eksport CSV.

## Reguły (bez typu umowy)

Decyzja Piotra z 13.11.2026: aplikacja nie zna typu umowy i nie wbudowuje ograniczeń umowy o pracę ani Kodeksu pracy. Nie ingeruje w to; kierownik sam ustawia wszystko w zasadach lokalu i może pisać prośby tekstem (np. "doświadczony kelner zawsze z niedoświadczonym").
- Zawsze twarde są tylko: "nie mogę", właściwe stanowisko, brak nakładających się zmian, zmiany przypięte ręcznie, dni, które minęły, i zasady kierownika oznaczone "bez wyjątków".
- Osobiste maksimum i cel godzin ustawione przez kierownika są miękkie, chyba że kierownik oznaczy zasadę "bez wyjątków".
- Zasady dobrej praktyki: miękkie, włączone domyślnie, kierownik może każdą wyłączyć albo zamienić na twardą: min. 11 h między zmianami, max 6 dni pracy z rzędu, równy podział weekendów i zmian zamykających.
- Zasady czasu pracy w katalogu: "Godziny pracy w ciągu dnia" (domyślnie najwyżej 8 h) i "Wolne w tygodniu" (domyślnie co najmniej 35 h bez przerwy). Decyzja Piotra z 13.11.2026: są dobrą praktyką, czyli włączone jako miękkie w nowych i istniejących lokalach; kierownik może je wyłączyć albo oznaczyć "bez wyjątków". Dotyczą wszystkich osób lokalu. Odpoczynek dobowy to zasada "Odpoczynek między zmianami".
- Odpowiedzialność za zgodność grafiku z prawem pracy spoczywa na kierowniku; aplikacja tego nie sprawdza.

## Generator (najważniejsza część)

a) OR-Tools CP-SAT uruchamiany w workerze, nigdy w zapytaniu HTTP. Limit czasu na uruchomienie (np. 30 s), zwracamy najlepszy znaleziony wynik. Najwyżej 1-2 zadania solvera naraz w kolejce.
b) Cel: najpierw minimalizuj liczbę nieobsadzonych slotów, potem sumę kar za złamane miękkie zasady. Zasady menedżera ważą wobec próśb pracowników jak 80 do 20 (wartość w profilu wag lokalu lub grupy, niewidoczna w interfejsie). Gdy ludzi brakuje, grafik i tak powstaje, z wyraźnie zaznaczonymi dziurami.
c) Pierwsza wersja: 1 wariant. Zaprojektuj kod tak, żeby później dodać 3 warianty (proporcje 70/30, 80/20, 90/10, min. 15% różnych przypisań).
d) Ocena pokazywana menedżerowi to trzy osobne wartości, liczone tym samym wzorem dla każdego wariantu: liczba nieobsadzonych slotów, ocena "zasady menedżera" w % (zasady lokalu, zasady dobrej praktyki, cel godzin) i ocena "prośby pracowników" w % ("chętnie" z kalendarza oraz prośby tekstem). Ocena grupy = 100 * (1 - suma(w_i * v_i) / suma(w_i)), gdzie v_i to stopień naruszenia 0-1. Grafik z dziurami jest oznaczony jako niekompletny i nie może wyglądać na dobry.
e) Niezależny walidator w Pythonie (osobny od solvera, pytest z przypadkami granicznymi) sprawdza każdy wariant i ma ostatnie słowo. Ten sam walidator obsługuje endpoint walidacji przy ręcznej edycji.
f) Stabilność: przy ponownym generowaniu w trakcie okresu kara za każdą zmianę względem opublikowanego grafiku, żeby jedna nieobecność nie przetasowała całego miesiąca. Dni, które minęły, są zamrożone.
g) Wyjaśnienia: szybkie sprawdzenie bezpośrednich przyczyn (dyspozycyjność, limit godzin, odpoczynek, stanowisko) bez ponownego uruchamiania solvera dla każdej prośby. Głębsza analiza tylko na żądanie menedżera.
h) Kierownik dostosowuje generator poleceniami tekstem do asystenta (LLM): zasady, ich ważność, powiązania między lokalami i poprawki wyniku; asystent zamienia polecenie na ustawienia z katalogu zasad, nigdy nie układa grafiku sam. Docelowo wszystko ma być ustawialne poleceniem. Prośby pracowników LLM zamienia na strukturę: typ z zamkniętej listy (unikaj_osoby, preferuj_osobe, typ_zmiany, limit_godzin, wolne_dni, inne; wolne_dni = "wolę nie pracować w te dni", miękko, bo twarde "nie mogę" zaznacza się w kalendarzu), kogo dotyczy, daty, poziom (bardzo_wazne / wazne / mile_widziane), pewność 0-1, opis jednym zdaniem. Do LLM wysyłaj tylko treść prośby i imiona z danego lokalu. Bez klucza API (zmienna ANTHROPIC_API_KEY) lub przy niskiej pewności prośba trafia do menedżera bez interpretacji.

## Logowanie i zaproszenia

- Wyłącznie kod SMS, bez haseł, Google i e-maila. Tożsamość to numer +48 (normalizacja biblioteką phonenumbers). Kod 6 cyfr, ważny 5 minut, max 5 prób; sesja ok. 60 dni.
- Kody wysyłamy tylko na numery +48, które mają konto albo oczekujące zaproszenie, oraz przy rejestracji nowego menedżera. Limity: kilka kodów na numer na godzinę i limit na adres IP.
- Lokalnie kod wypisywany w konsoli. Prawdziwa bramka SMS (np. SMSAPI.pl) za wymienialnym interfejsem, dopiero przy wdrożeniu.
- Menedżer zaprasza pracownika po numerze telefonu: wiersz w tabeli invitations ze statusem (oczekuje / przyjęte / odrzucone / anulowane), unikalne oczekujące zaproszenie na parę (placówka, numer). SMS z zaproszeniem NIE jest wysyłany. Pracownik po zalogowaniu widzi zaproszenie: Akceptuj / Odrzuć; akceptacja w jednej transakcji. Kto ma już konto, widzi nowe zaproszenie od razu.
- Limity dokładnie: kolejny kod najwcześniej po 60 s, najwyżej 5 kodów na numer na godzinę i 20 próśb o kod z jednego adresu IP na godzinę (liczą się też prośby dla nieznanych numerów). Nowy kod unieważnia poprzedni. W bazie jest tylko skrót kodu.
- Nieznany numer przy logowaniu dostaje jasną odpowiedź ("Nie znamy tego numeru. Poproś kierownika o zaproszenie…"), a nie udawane wysłanie kodu: dla osób niechętnych technologii czekanie na SMS, który nie przyjdzie, jest gorsze niż ryzyko, że ktoś sprawdzi, czy numer ma konto (to ryzyko ogranicza limit na adres IP).
- Zapraszając, menedżer może od razu wpisać imię i nazwisko; trafiają na konto przy akceptacji, jeśli konto nie ma jeszcze imienia. Pracownika zaprasza menedżer lokalu, menedżera zaprasza tylko właściciel firmy. Akceptacja zaproszenia pracownika tworzy członkostwo w firmie i profil pracownika z tym lokalem jako domowym.
- Zmiana numeru telefonu: robi ją superadmin w panelu. Konto, członkostwa i historia zostają; wszystkie sesje tego konta wygasają i trzeba zalogować się nowym numerem. Zaproszenia oczekujące na stary numer menedżer wysyła ponownie. Numery spoza Polski: poza prototypem.
- Poza kodami logowania nic nie wysyłamy SMS-em ani e-mailem. Powiadomienia tylko w aplikacji.

## Dostęp i subskrypcja (bez płatności online, bez Stripe)

- Kody na darmową subskrypcję generuje superadmin w panelu admina Django: długość dostępu 30 albo 60 dni, maksymalna liczba użyć (domyślnie 1), opcjonalna data ważności samego kodu, notatka (np. nazwa firmy).
- Kod losowy, min. 10 znaków bez mylących znaków (0/O, 1/l), wielkość liter bez znaczenia; limit prób wpisania.
- Kod wpisuje kierownik przy zakładaniu firmy albo później w ustawieniach. Subskrypcja dotyczy całej firmy; pracownicy niczego nie wpisują.
- Tabela subscriptions niezależna od dostawcy płatności: firma, status (aktywna / wygasła), data końca, źródło ("kod", w przyszłości "stripe"). Kolejny kod przedłuża dostęp od daty końca, nie od dnia wpisania.
- 7 dni przed końcem baner w panelu kierownika. Po wygaśnięciu tryb tylko do odczytu: grafik widoczny, bez edycji i generowania. Danych nie usuwamy.
- Firma założona bez kodu dostaje 30 dni okresu próbnego z pełnym dostępem (decyzja Piotra z 12.11.2026; 13.11.2026 wydłużone z 14 do 30 dni, żeby zmieścił się pełny miesięczny cykl: dyspozycje, termin, ułożenie, publikacja). Okres próbny dostaje tylko pierwsza firma zakładana przez daną osobę; limit ułożeń grafiku obowiązuje także wtedy. Po okresie próbnym firma jest tylko do odczytu, dopóki kierownik nie wpisze kodu; kod wpisany w okresie próbnym dolicza swoje dni do końca okresu próbnego, więc nic nie przepada.
- W trybie tylko do odczytu każda zmiana danych firmy jest odrzucana (HTTP 402 z komunikatem po polsku); wyjątki: wpisanie kodu, odpowiedź zaproszonej osoby na zaproszenie oraz oznaczenie własnych powiadomień jako przeczytane (pracownik nadal widzi grafik i powiadomienia; oddawać ani brać zmian nie można).
- Limit prób wpisania kodu: 5 błędnych na konto i 20 na adres IP w ciągu godziny. Kod ma 12 znaków, pokazywany w grupach po 4 (ABCD-EFGH-JKMN); spacje i myślniki nie mają znaczenia. Jeden kod można użyć w danej firmie tylko raz. Kody widać w całości tylko raz, zaraz po wygenerowaniu; w bazie jest skrót i pierwsze 4 znaki.
- Limit generowań grafiku na firmę (roboczo 30 na miesiąc), także w okresie darmowym.

## Stos

- Backend w całości w Pythonie: Django + Django Ninja (OpenAPI), PostgreSQL, migracje Django, sesje Django + własny moduł logowania kodem SMS.
- Kolejka: Procrastinate na Postgresie (bez Redisa i RabbitMQ), osobny proces worker z tego samego kodu. Zapis danych i dodanie zadania do kolejki w jednej transakcji.
- Frontend w TypeScripcie, bez Next.js: React + Vite (SPA), TanStack Router + TanStack Query, Tailwind + shadcn/ui, React Hook Form + Zod, dnd-kit. Klient API generowany z OpenAPI (orval).
- Docker Compose: Django, worker, Postgres, Caddy. Caddy serwuje frontend i przekazuje /api do Django pod jedną domeną. Na razie uruchamiane lokalnie; wdrożenie na jeden serwer VPS ma być później jednym krokiem.

## UX i wygląd

- Zanim powstanie pierwszy ekran, przygotuj plik z kierunkiem wizualnym i tokenami (kolory, typografia, odstępy, promienie, rozmiary dotyku) i zaczekaj na moją akceptację. Zaakceptowany 12.11.2026 kierunek "kartka z zaplecza": spokojne chłodne tło jak papier, jeden niebieski akcent jak z długopisu, kratka tylko tam, gdzie się zaznacza, najbliższa zmiana jak kartka z kalendarza zdzieraka; krój Atkinson Hyperlegible Next. Tokeny: `frontend/src/styles/tokens.css`. Wszystkie ekrany korzystają wyłącznie z tych tokenów. Komponenty shadcn/ui są ostylowane tokenami, nie zostają w wyglądzie domyślnym.
- Bez generycznego wyglądu: żadnych fioletowych gradientów, szklanych efektów, emoji jako ikon, kart w kartach ani pulpitu pełnego kafelków ze statystykami. Jeden kolor akcentu, krój pisma z charakterem i dobrą czytelnością polskich znaków, spokojne tło.
- Pracownik ma dwa ekrany: "Mój grafik" i "Kiedy mogę". Elementy dotykowe min. 48 px, tekst podstawowy min. 18 px (treść, główne przyciski, nawigacja i nagłówek; 16 px tylko dla podpisów pomocniczych pod tytułem lub przyciskiem oraz etykiet czterech stanów w pasku pędzla, które muszą się zmieścić obok siebie na telefonie 360 px; 15 px tylko dla nazw dni tygodnia nad kalendarzem, etykiet tygodni i godzin w kafelku dnia, które widać też w pełnym rozmiarze w liście „Dni z godzinami”), wysoki kontrast, zwykłe słowa, brak ukrytych gestów, każda akcja do cofnięcia, natychmiastowa reakcja na dotknięcie.
- Stany dyspozycyjności odróżnia nie tylko kolor, ale też ikona lub wzór i podpis.
- Każdy ekran ma zaprojektowany stan pusty, stan ładowania i stan błędu, z tekstami w ludzkim języku.
- Dane przykładowe i teksty mają być prawdziwe: polskie imiona, realne godziny zmian, realne stanowiska.
- Po każdym etapie z ekranami dołącz do pull requesta zrzuty ekranu w szerokości telefonu i komputera.

## Dane przykładowe

Firma z 4 piekarniami w jednej grupie i jednym menedżerem, 15-25 pracowników na lokal, dyspozycyjność na kolejny miesiąc, 20-30 próśb tekstem i kilka zasad menedżera, w tym sprzeczne ze sobą. Druga, osobna firma do sprawdzenia izolacji danych.

## Poza pierwszą wersją

Trzy warianty grafiku, zamiany zmian, wnioski urlopowe, zadania na zmianie, koszt pracy, rejestracja czasu pracy, miesięczne zestawienie przepracowanych godzin zleceniobiorców, płatności, aplikacje iOS i Android, wysyłka SMS przez bramkę.

## Sposób pracy

1. Najpierw krótki plan do mojej akceptacji: architektura, modele danych, lista endpointów, lista ekranów i podział na etapy.
2. Etapy, każdy jako osobny pull request z testami:
   1) szkielet repozytorium, Docker Compose, CLAUDE.md, docs/spec.md;
   2) modele danych, izolacja firm, dane przykładowe;
   3) logowanie kodem SMS, zaproszenia, kody subskrypcji;
   4) walidator z testami przypadków granicznych;
   5) generator w workerze z testami;
   6) kierunek wizualny i tokeny, potem ekrany pracownika;
   7) ekrany menedżera: ustawienia lokalu, dyspozycje, zasady;
   8) generowanie, ocena, wyjaśnienia, ręczna edycja, publikacja;
   9) oddawanie zmiany i powiadomienia w aplikacji;
   10) interpretacja próśb przez LLM.
3. Testy obowiązkowe: walidator twardych reguł i zasad czasu pracy z katalogu (odpoczynek, godziny w ciągu dnia, wolne w tygodniu); generator nie łamie twardych reguł; limit czasu działa; stabilność przy ponownym generowaniu; izolacja firm; logowanie i limity kodów; kody subskrypcji.
4. Na końcu README z instrukcją uruchomienia i listą uproszczeń prototypu.

Jeśli coś jest niejasne, przyjmij rozsądne założenie, zapisz je i kontynuuj.
