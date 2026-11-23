# Grafikomat: specyfikacja prototypu

Źródło prawdy dla zakresu prototypu. Gdy decyzja się zmienia, najpierw poprawiamy ten plik, potem kod.
Plan techniczny (architektura, modele, endpointy, ekrany, etapy): [plan.md](plan.md).
Założenia przyjęte przy planowaniu są w sekcji "Założenia" na końcu planu.

## Zapraszanie wielu osób naraz (prośba Piotra z 23.11.2026)

Prośba Piotra: „dodaj też możliwość zaproszenia wielu pracowników na raz. niech asystent ai ma możliwość przyjęcia
pliku np pdf albo csv i sparsowania tego i wrzucenia do apki”.

- „Pracownicy” lokalu → „Zaproś kilka osób”: kierownik wkleja listę (jedna osoba w wierszu: imię, nazwisko, numer,
  może być stanowisko i lokal) albo wybiera plik CSV, Excel (.xlsx) lub PDF z tekstem (do 2 MB). Aplikacja sama, bez
  asystenta, znajduje w nim osoby: wiersz z numerem telefonu to osoba, a gdy plik ma wiersz nagłówków („Imię”,
  „Nazwisko”, „Telefon”, „Stanowisko”, „Lokal”), kolumny mówią, co jest czym. Stanowiska i lokale rozpoznaje po
  nazwie (także po samym „Wieliczka”, gdy tylko jeden lokal ma to słowo).
- Przed wysłaniem kierownik widzi listę: imię, numer, stanowiska, lokal (gdy inny niż ten) i przy każdej osobie, co
  przeszkadza (brak numeru, zły numer, już pracuje w tym lokalu, ma już zaproszenie, numer powtarza się na liście).
  Każdą osobę może poprawić („Popraw”: imię, nazwisko, numer, stanowiska) albo usunąć z listy. „Zaproś N osób”
  zaprasza gotowe osoby; te, których nie dało się zaprosić, zostają na liście z powodem.
- Zaproszenie może mieć stanowiska: po przyjęciu zaproszenia osoba dostaje je w tym lokalu (tylko stanowiska, które
  lokal nadal ma). Lista „Czekają na odpowiedź” pokazuje je przy numerze.
- Asystent kierownika: spinacz przy polu wiadomości (i podpowiedź „Zaproś ludzi z pliku” w pustej rozmowie) dołącza
  plik. Asystent czyta listę także w innym układzie (np. nazwisko przed imieniem, imię i numer w osobnych wierszach,
  „kasjerka” zamiast „Kasa”) i proponuje zaproszenia jak każdy plan: lista „Zaproszę: Anna Kowalska, 512 345 678,
  Kasa.”, uwagi o osobach pominiętych i „Zatwierdź zmiany”. Nic się nie zapisuje przed zatwierdzeniem. Tak samo działa
  zwykła wiadomość („zaproś Annę Kowalską 512 345 678 na kasę”).
- Asystent nie widzi numerów telefonów: aplikacja zastępuje je znacznikami ([TEL1]…), a w planie wstawia z powrotem
  numery z wiadomości albo pliku. Asystent nie może więc wymyślić ani przekręcić numeru. Z pliku zostaje w aplikacji
  tylko nazwa: jego tekst znika, gdy asystent go przeczyta.
- Osoba, której nie da się zaprosić, nie blokuje całej listy (inaczej niż przy zasadach): plan zaprasza resztę i
  mówi, kogo pominął i dlaczego. Kto zostanie zaproszony w międzyczasie, jest pomijany przy zatwierdzeniu.
- Kierownik zaprasza tylko do lokali, którymi zarządza; kierownika (osoba opisana w pliku jako kierownik) zaprasza
  tylko właściciel firmy, tylko przez asystenta. Jak dotąd SMS-a z zaproszeniem nie ma: zaproszeni logują się swoim
  numerem.
- Naraz najwyżej 300 osób z ekranu i 100 z asystenta (dłuższą listę trzeba podzielić).

## Koszty asystenta (prośba Piotra z 22.11.2026)

Piotr chce wiedzieć, ile płaci za OpenRouter: za każde konto i każdy lokal, a u kierownika osobno za rozmowy
z asystentem i za układanie grafiku.

- Model językowy (OpenRouter, zapasowo Claude) czyta tylko wiadomości do asystenta: pracownika (prośby i pytania)
  i kierownika (polecenia i pytania w czacie). Grafik układa solver OR-Tools na naszym serwerze, więc układanie nie
  kosztuje nic za użycie, tylko zajmuje serwer (w cenie VPS). „Ułóż inny grafik” z czatu to wiadomość (koszt modelu)
  plus układanie (czas solvera).
- Każda wiadomość, którą przeczytał model, zostawia jeden zapis: firma, lokal, osoba, która napisała, rodzaj
  (pracownik albo kierownik), model, dostawcy, liczba zapytań do API, tokeny, koszt w USD (z `usage.cost`, który
  OpenRouter podaje przy każdej odpowiedzi) i czy odpowiedź się udała. Nieudana odpowiedź też kosztuje, więc też
  zostaje zapisana. Claude nie podaje kosztu: jego zapis ma tylko tokeny i liczy się jako „bez ceny”.
- Lokal wiadomości pracownika to lokal okresu, a dla prośby na miesiąc (bez okresu) główny lokal osoby. Lokal
  wiadomości kierownika to lokal czatu.
- Układanie grafiku to każde uruchomienie solvera: kto poprosił, dla którego lokalu i ile trwało. Wspólne układanie
  grupy lokali liczy się w każdym jej lokalu, a jego czas dzieli się między nie po równo.
- Zestawienie miesiąca (firmy, lokale, osoby) widzi tylko superadmin: w panelu admina Django („Koszty asystenta”,
  przycisk „Zestawienie miesiąca”) i w pliku CSV (`manage.py assistant_costs --month 2026-11`). Kierownicy
  i pracownicy nie widzą kosztów, a model językowy nigdy ich nie czyta.
- Liczenie zaczyna się od wdrożenia: wcześniejszych wiadomości nie da się przypisać do osób, bo koszt był tylko
  w logu workera. Zestawienie pokazuje to, co schodzi z kredytów OpenRouter; opłaty OpenRoutera za doładowanie konta
  w nim nie ma.

## Inny grafik na prośbę kierownika (prośba Piotra z 22.11.2026)

Prośba Piotra: gdy ułożony grafik z jakiegoś powodu nie pasuje kierownikowi, ma się dać ułożyć nowy, wyraźnie inny,
także według jego prośby słowami. Wcześniej „Ułóż od nowa” przy tych samych ustawieniach dawało prawie ten sam grafik,
bo generator znowu szukał najlepszego, a najlepszy się nie zmienił.

- „Ułóż inaczej” w zakładce „Grafik”, obok „Ułóż od nowa” (gdy okres ma już grafik). Działa jak „Ułóż od nowa”:
  zostają przypięte zmiany, osoby wpisane mimo przeszkód i minione dni, nieprzypięte ręczne poprawki znikają,
  „Anuluj” działa. Do tego generator dostaje warunek: co najmniej 30% zmian każdej
  wcześniejszej wersji okresu (bez przypiętych i minionych) ma w nowym grafiku inną osobę. Liczy się, kto
  pracuje danego dnia na danej zmianie i stanowisku; dwie osoby zamienione miejscami na tej samej zmianie to nie
  różnica. Porównanie ze wszystkimi wersjami (technicznie do 100 najnowszych), bo kierownik może klikać „Ułóż
  inaczej” do skutku, aż grafik mu się spodoba: każde kliknięcie ma dać nowy grafik, a nie wracać do dwóch czy
  trzech tych samych (Piotr, 22.11.2026: 30% zostaje).
- Kolejność ważności: najpierw jak najmniej zmian bez obsady (nigdy więcej niż przy zwykłym układaniu), potem różnica
  (do 30%), potem zasady i prośby jak zawsze. Twarde reguły i zasady „bez wyjątków” obowiązują jak zawsze. Gdy 30%
  się nie da (np. tylko jedna osoba umie piec), grafik jest tak inny, jak się da.
- „Uwagi” nowego szkicu mówią, ile zmian ma inne osoby niż w wersji, którą kierownik widział („Ułożony inaczej niż
  wersja 3: inne osoby na 31 z 90 zmian.”), czy od starszych wersji też różni się co najmniej co trzecią zmianą (albo
  od której mniej), a gdy 30% się nie udało, że bardziej się nie dało przy tych ustawieniach. Gdy zasady kierownika
  albo prośby pracowników wyszły słabiej niż w tamtej wersji, uwaga to mówi („Słabiej niż w wersji 3: zasady
  kierownika 85,5 % zamiast 90 %.”), bo różnica idzie przed nimi. Okno mówi to z góry jednym zdaniem.
- Wszystkie szkice zostają (Piotr, 22.11.2026): każda ułożona wersja jest na liście „Wersje”, a usuwa ją tylko kosz.
  Do starszego szkicu da się wrócić przyciskiem „Wróć do tej wersji”: aplikacja robi z niego nowy szkic (kolejny
  numer, na liście „jak wersja 5”), z jego osobami, przypięciami i ręcznymi poprawkami, a obecny szkic zostaje na
  liście. Dotyczy szkiców ułożonych po ostatniej publikacji (do szkicu sprzed publikacji się nie wraca, bo minione
  dni opublikowanego grafiku już się wydarzyły) i nie działa w trakcie układania.
- Okno przed ułożeniem mówi to jednym zdaniem, ostrzega o ręcznych poprawkach jak przy „Ułóż od nowa” i mówi, że
  gorszy szkic można usunąć koszem, a wtedy wraca obecny (razem z ręcznymi poprawkami, bo zostają w obecnej
  wersji). Ułożeń grafiku nie ogranicza żaden limit i aplikacja ich nie liczy (decyzja Piotra z 22.11.2026: kierownik
  klika „Ułóż inaczej”, ile chce; tego samego dnia mechanizm limitu został usunięty z kodu). Przed publikacją ma też „Napisz asystentowi”, który otwiera czat z tym okresem, gdy kierownik wie, co ma
  być inaczej (po publikacji ustalenia okresu są zamknięte, więc czat by odmówił).
- Według prośby kierownika: w czacie kierownik pisze np. „Ten grafik mi nie pasuje, ułóż inny, żeby Ania miała mniej
  porannych zmian”. Plan ma wtedy zwykłe zmiany (polecenie o Ani, zasady) i ostatni punkt „Po zatwierdzeniu ułożę
  nowy grafik na okres …, wyraźnie inny niż obecny.” Po „Zatwierdź zmiany” ustalenia się zapisują i od razu rusza
  układanie („Anuluj” działa), a czat pokazuje postęp i link do szkicu. Gdy kierownik prosi tylko o ułożenie
  jeszcze raz po zmianach („zmień to i ułóż od nowa”), ostatni punkt to „Po zatwierdzeniu ułożę grafik na okres …
  od nowa.”, bez warunku różnicy. Samo „ułóż inny grafik” bez innych zmian też jest planem do zatwierdzenia.
- Asystent nadal niczego nie układa sam: punkt o układaniu dodaje tylko na wyraźną prośbę kierownika, a układanie
  rusza dopiero po „Zatwierdź zmiany”. Dotyczy wyłącznie okresu ustaleń, który ma już grafik. Gdy okres nie ma
  jeszcze grafiku, grafik właśnie się układa albo ustalenia nie mają okresu, plan nie przechodzi w całości (jak każda
  niewykonalna część), a asystent mówi, co zrobić. Gdy lokal ma opublikowany grafik, który jeszcze trwa, mówi też,
  że ten grafik ułoży inaczej przycisk „Ułóż inaczej” w zakładce „Grafik”. Gdy przy zatwierdzeniu układanie nie może ruszyć (np. trwa inne
  układanie), nic z planu się nie zapisuje.

## Oczekiwana wypłata (prośby Piotra z 22.11.2026)

Pracownik widzi przy sumie godzin w miesiącu, ile zarobi, a kierownik widzi, ile wypłacić każdej osobie i wszystkim
razem. Piotr zawsze na to patrzył w Kadromierzu. Wypłata to dokładne wyliczenie z grafiku i stawek, więc ekrany nie
nazywają jej szacunkiem (prośba Piotra).

- Stawka za godzinę należy do stanowiska: kierownik wpisuje ją w ustawieniach lokalu, przy stanowiskach (np. Sprzedawca
  31,40 zł, Piekarz 36 zł). Stanowisko bez stawki działa jak dotąd. Stawki widzi tylko kierownik.
- Osoba może mieć własną stawkę na stanowisku: kierownik wpisuje ją w formularzu pracownika, w zwijanej części
  „Stawki”. Bez własnej stawki liczy się stawka stanowiska. Stanowiska należą do lokalu, więc w każdym lokalu osoby jej
  stawki ustawia kierownik tego lokalu.
- Stawka „od dnia” (prośba Piotra): zmiana stawki stanowiska albo osoby działa dopiero od wybranego dnia. Zmiany
  wcześniejsze liczą się po starej stawce, więc minione miesiące się nie zmieniają. Pierwsza stawka stanowiska liczy się
  dla wszystkich zmian, bo wcześniej żadnej nie było. Własna stawka osoby zawsze ma dzień, także pierwsza, bo
  wcześniej liczyła się stawka stanowiska. Zmianę można wpisać z góry (np. podwyżka od 1 stycznia), a pomyłkę
  usunąć: wtedy znów liczy się poprzednia stawka. O stawce zmiany decyduje dzień, w którym zmiana się zaczyna.
  Stawka albo dodatek od dnia w minionym miesiącu i usunięcie stawki, która już działała przed tym miesiącem, zmieniają
  wypłatę, która mogła być już wypłacona: ekran mówi wtedy „To zmieni wypłatę za minione miesiące.”, a usunięcie
  takiej stawki pyta najpierw (uwaga Prelint z 22.11.2026). Czy zamykać minione miesiące, sprawdzimy w pilotażu.
  Własne stawki osoby zapisują się od razu, osobno od przycisku „Zapisz” formularza, i ekran to mówi.
- Doświadczenie na stanowisku (prośba Piotra, tak jak w Kadromierzu): kto ma dłuższy staż, dostaje własną stawkę na
  tym stanowisku od dnia, np. piekarz po roku 38 zł od 1 marca. Ta sama osoba może więc zarabiać różnie na różnych
  stanowiskach i w różnych miesiącach. Stopień doświadczenia z formularza („początkujący”, „samodzielny”,
  „doświadczony”) służy do układania grafiku i nie ma daty, więc stawki nie zmienia: inaczej awans przeliczyłby
  minione miesiące.
- Dodatki za porę dnia (prośba Piotra): kierownik dodaje je w ustawieniach lokalu, np. „Noc 22:00–06:00, +6 zł za
  godzinę” albo „Niedziela, cały dzień, +50% stawki”. Dodatek ma godziny (mogą przechodzić przez północ), dni tygodnia,
  kwotę w złotych za godzinę albo procent stawki zmiany, i wszystkie stanowiska albo wybrane. Liczy się tylko część
  zmiany w tych godzinach: zmiana 20:00–04:00 dostaje 6 godzin dodatku nocnego. Dzień tygodnia to dzień, w którym
  zaczynają się godziny dodatku (noc z soboty na niedzielę to sobota). Kilka dodatków w tej samej godzinie się sumuje.
  Dodatek dotyczy tylko godzin ze stawką. Zmiana albo usunięcie dodatku też działa od wybranego dnia. Świąt aplikacja
  nie zna, więc dodatku za święto na razie nie ma.
- Wypłata to godziny, które się liczą (z opublikowanych grafików, z zatwierdzonymi nadgodzinami i krótszymi zmianami,
  tak jak na ekranie „Godziny”), razy stawka danej zmiany, plus dodatki. To kwota brutto: aplikacja nie zna umowy, więc
  nie liczy podatku, składek ani premii.
- Pracownik: w „Mój grafik” pod „Razem w listopadzie” jest „Wypłata brutto” za wszystkie opublikowane zmiany tego
  miesiąca (także te, które są jeszcze przed nim) we wszystkich jego lokalach, a pod nią „w tym dodatki”, gdy są. Gdy
  żadna zmiana nie ma stawki, tej linii nie ma. Gdy części zmian brakuje stawki, linia mówi, ilu godzin nie liczy.
- Kierownik: ekran „Godziny” ma kolumnę „Wypłata brutto” na osobę i sumę dla wszystkich (z lokali, które prowadzi), a
  plik CSV kolumny „Wypłata brutto, zł”, „W tym dodatki, zł” i „Godziny bez stawki”. Gdy w miesiącu żadna zmiana nie ma
  stawki, ekran mówi jednym zdaniem, gdzie ją ustawić. W trwającym miesiącu podpis mówi, że kwota obejmuje też zmiany,
  które dopiero będą. Przy osobie, która pracuje też w lokalach innego kierownika, uwaga przy kwocie mówi, że brak w
  niej innych lokali (uwagi Prelint z 22.11.2026).
- Własna stawka zostaje, gdy osoba traci stanowisko albo odchodzi z lokalu, żeby jej dawne zmiany liczyły się tak jak
  wcześniej.
- Asystent nie zna kwot: wypłaty, stawki i dodatki nie trafiają do zewnętrznej usługi AI (uwaga z przeglądu Prelint z
  22.11.2026: to dane wrażliwsze niż godziny, a ekrany o tym nie mówią). Na „ile zarobię w listopadzie?” odpowiada,
  gdzie to sprawdzić.

## Asystent przez OpenRouter (decyzja Piotra z 21.11.2026)

Piotrowi skończył się limit Claude API, więc asystent łączy się przez OpenRouter (jeden klucz, wiele modeli) z modelem
DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash`). Działanie dla ludzi się nie zmienia: te same polecenia, prośby,
odpowiedzi, odczyty danych przez API i pamięć 10 wiadomości.

- Klucz `OPENROUTER_API_KEY`, model `OPENROUTER_MODEL` (dowolny model z openrouter.ai/models, który umie wywoływać
  narzędzia), głębokość myślenia `OPENROUTER_EFFORT` (domyślnie `low`). Claude zostaje jako druga droga do wyboru: gdy nie ma
  klucza OpenRouter, a jest `ANTHROPIC_API_KEY`, asystent używa Claude jak dotąd. Gdy są oba, wygrywa OpenRouter.
- OpenRouter wysyła zapytanie do jednego z wielu dostawców tego modelu. Aplikacja dopuszcza tylko dostawców, którzy nie
  zapisują i nie uczą się na treści zapytań (`data_collection: deny`), bo w wiadomościach są imiona i grafiki ludzi.
- Claude nie przejmuje rozmowy sam: gdy OpenRouter zawiedzie (np. brak środków, błąd 402), wiadomość idzie zwykłą
  drogą błędu (prośba do kierownika, polecenie „asystent nie dał rady”, ślad w `assistant_misses`), nawet jeśli jest
  też klucz Claude. Tak samo jak decyzja z 20.11.2026 o braku automatycznej zmiany modelu, a dane nie trafiają po
  cichu do drugiego podmiotu. Zmiana usługi to zmiana klucza w `.env`.
- Ekrany nie wymieniają już nazwy usługi („Claude”), tylko mówią „zewnętrzna usługa AI”, bo model można zmienić bez
  zmiany kodu.
- Jakość sprawdzona 21.11.2026 powtórką całego testu z 20.11 (52 wiadomości, plik
  `testy-asystenta/deepseek-powtorka-2026-11-21.md` w projekcie): zachowanie jak u Claude, dane w odpowiedziach
  zgodne z bazą, mediana 4,8 s. Próg pewności 0,6 zostaje; pilnuje go lista pomyłek (`assistant_misses`).
- Warunki przed wpuszczeniem prawdziwych pracowników (razem z bramką SMS, jak w `docs/deploy.md`): polityka
  prywatności wymienia OpenRouter i dostawców modelu jako podmioty przetwarzające (wcześniej: Anthropic), a test
  asystenta powtarza się na prawdziwych sformułowaniach z pilotażu i przegląda listę pomyłek.

## Prośby na stałe (prośba Piotra z 22.11.2026)

Dotąd prośba pracownika działała tylko w okresie (albo miesiącu), na który ją napisał, więc w następnym miesiącu
trzeba było pisać ją od nowa. Teraz prośba może obowiązywać na stałe.

- Prośba na stałe liczy się w swoim okresie (miesiącu) i w każdym kolejnym okresie grafiku, aż pracownik albo
  kierownik ją zakończy. Jak prośba na miesiąc dotyczy osoby, więc liczy się w każdym lokalu, w którym ta osoba
  pracuje. Generator bierze z niej w kolejnych okresach tylko to, co jest bez dat (dni tygodnia, osoba, zmiana,
  limit); konkretne dni zostają w swoim miesiącu.
- Asystent sam rozpoznaje, jak długo prośba ma obowiązywać. Prośba ogólna, bez dat („nie pracuję w piątki”, „nie
  stawiajcie mnie z Zuzanną”, „najwyżej 3 nocki w tygodniu”) jest na stałe. Prośba z konkretnymi dniami, powiązana
  z tym miesiącem („w grudniu”, „w tym miesiącu”) albo z chwilowym powodem (sesja, remont, choroba) jest tylko na
  ten okres. Gdy pracownik sam mówi, że to na jakiś czas, ale nie wiadomo, czy dłużej niż ten miesiąc („na razie”,
  „przez jakiś czas”), asystent pyta: „Czy to tylko na grudzień, czy na stałe?”.
- W „Twoich prośbach” przy każdej zapisanej prośbie są dwa przyciski: „Tylko grudzień” (albo dni okresu) i „Na
  stałe”. Wybrany jest zaznaczony, a drugi przełącza jednym stuknięciem, dopóki prośbę można poprawić. Prośba tylko
  z konkretnymi dniami nie ma tego wyboru. Prośba, którą czyta kierownik, też może być na stałe: wtedy widzi ją
  w każdym kolejnym okresie.
- W kolejnych miesiącach prośba na stałe jest w „Twoich prośbach” z dopiskiem „Na stałe od grudnia” i przyciskiem
  „Zakończ” (drugie stuknięcie: „Tak, zakończ”). Zakończona nie liczy się od okresu (miesiąca) na ekranie;
  wcześniejsze zostają bez zmian. Zostaje w tym okienku jako zakończona, z „Przywróć”, gdyby to była pomyłka.
  Treść poprawia się albo usuwa w miesiącu, w którym prośbę napisano (dopóki jest otwarty); później zamiast tego
  kończy się ją i pisze nową. Czat innego miesiąca jej nie pokazuje (to rozmowa tamtego miesiąca), ale asystent ją
  zna: gdy pracownik ją zmienia („od stycznia jednak soboty, nie piątki”), asystent zapisuje nową prośbę, a starą
  kończy od tego miesiąca. Gdy pracownik pisze tylko, że prośba już nie obowiązuje, asystent mówi, gdzie ją
  zakończyć.
- Kierownik widzi przy prośbie w „Dyspozycjach” znacznik „Na stałe”, a przy prośbie z wcześniejszego okresu „Na
  stałe od grudnia”. Taką prośbę może zakończyć od okresu na ekranie („Zakończ od tego okresu”); pracownik dostaje
  o tym powiadomienie. Zakończona zostaje na liście tego okresu z dopiskiem, kto ją zakończył, a kierownik może ją
  przywrócić, jeśli to on ją zakończył. Odrzucenie i ważność nadane przez kierownika dotyczą prośby we wszystkich
  okresach, w których obowiązuje.
- Prośby napisane przed tą zmianą działają jak dotąd tylko w swoim okresie (miesiącu). Pracownik może przełączyć je
  na „Na stałe”, dopóki ich okres jest otwarty.

## Asystent pracownika dopytuje (prośba Piotra z 22.11.2026)

Dotąd prośba, której asystent nie był pewny, od razu szła do kierownika bez interpretacji. Teraz asystent najpierw
dopytuje pracownika, a kierownikowi zostawia tylko to, czego po doprecyzowaniu nadal nie da się zapisać.

- Gdy asystent nie wie, o który dzień, osobę, zmianę albo ile chodzi, albo prośba nie pasuje do żadnego typu, ale
  jeden szczegół może to zmienić, zadaje jedno krótkie pytanie i niczego z tej wiadomości nie zapisuje (żadnej
  preferencji, także tych, których był pewny). Przykłady: „chcę mniej pracować” (ile godzin albo dni?), „nie mogę
  z Anią”, gdy w lokalu są dwie Anie (Ania K. czy Ania M.?), „po zabiegu kolana nie mogę dźwigać blach przez dwa
  tygodnie” (od kiedy? czy chodzi o konkretne zmiany?). Gdy w prośbie jest imię kilku osób z lokalu, aplikacja
  sama zadaje to pytanie, nawet jeśli model go nie zadał.
- Aplikacja sama pyta też w dwóch przypadkach, które dotąd szły od razu do kierownika (dopisane 22.11.2026 po
  prośbie Piotra „żeby asystent był pewien na 100%”): gdy asystent sam wątpi w swój odczyt (pewność poniżej 0,6),
  pyta „Czy dobrze rozumiem: wolne w piątki? Odpisz „tak” albo napisz, co poprawić.”; gdy odczyt wskazuje osobę
  albo zmianę, której nie ma w lokalu, pyta, o kogo albo o którą zmianę chodzi (z podobnymi imionami albo listą
  zmian). W odpowiedzi na pytanie aplikacja pyta tak samo, w ramach limitu pytań niżej. Samo „tak” (też „tak,
  dokładnie”, „zgadza się”) na „Czy dobrze rozumiem…” zapisuje ten odczyt i o pewność już nie pyta (uwaga z przeglądu
  PR #68: jasne „tak” nie może zostać zignorowane); „tak, ale…” to poprawka i asystent czyta ją jak zwykle.
- Pytanie widać w czacie jak odpowiedź asystenta, z dopiskiem, że prośba nie jest zapisana, dopóki pracownik nie
  odpowie. Pole pisania podpowiada „Odpowiedz asystentowi…”. Pytanie nie trafia do kierownika, nie liczy się do
  limitu próśb i nie jest pomyłką w `assistant_misses`. Pod pytaniem zostaje „Niech przeczyta kierownik”, gdy
  pracownik woli nie odpowiadać.
- Odpowiedź asystent czyta razem z pierwszą wiadomością i pytaniem, i zapisuje pełne prośby z obu. Pytanie czeka
  (decyzja Piotra z 22.11.2026): pracownik może najpierw zapytać o grafik albo napisać inną prośbę, a odpowiedzieć
  później. Czeka tak długo, jak asystent pamięta rozmowę (10 ostatnich wiadomości); asystent widzi wszystkie
  czekające pytania z numerami i sam rozpoznaje, na które przyszła odpowiedź.
- Żeby taka prośba nie przepadła po cichu (uwaga z przeglądu PR #64), okienko „Twoje prośby” pokazuje każdą wiadomość
  z pytaniem bez odpowiedzi osobno, w przerywanej ramce: „Nie jest zapisana. Asystent pyta: …”. Dopóki asystent
  pamięta pytanie, jest przy niej „Odpowiedz” (otwiera czat); starszą zapisuje się przez „Napisz ją od nowa” (cała
  prośba razem z odpowiedzią; asystent czyta ją od początku). Przy każdej jest też „Niech przeczyta kierownik”.
- Pyta, aż wie na pewno (prośba Piotra z 22.11.2026), najwyżej trzy razy z rzędu o jedną prośbę (limit trzech
  pytań: decyzja Piotra z 22.11.2026; wcześniej asystent pytał tylko raz). Każdą odpowiedź czyta razem z wcześniejszymi wiadomościami tej prośby i pytaniami. Czego po trzecim pytaniu
  nadal nie da się zapisać, trafia do kierownika jak dotąd (powód „asystent nie był pewny”); pracownik czyta wtedy
  „Nadal nie wiem na pewno, o co chodzi, więc tego nie zapisuję. Kierownik przeczyta całą rozmowę.” Kierownik widzi przy
  prośbie wszystkie wcześniejsze wiadomości, pytania asystenta i ostatnią odpowiedź. W „Twoich prośbach” wiadomość
  z kolejnym pytaniem pokazuje nad sobą wcześniejsze wiadomości tej prośby.
- Pytanie zadaje także wtedy, gdy wiadomość łączy pytanie o grafik z niejasną prośbą: odpowiada na pytanie i dopytuje
  o prośbę. Zgłoszenia innych godzin z tej wiadomości (z przyciskiem „Wyślij kierownikowi”) pokazuje jak dotąd.
- Działa tak samo przez OpenRouter i przez Claude: pytanie to pole odpowiedzi asystenta (`question`), a numer
  pytania, na które wiadomość odpowiada, to drugie pole (`answers_question`).

## Nadgodziny i krótsza zmiana (prośba Piotra z 20.11.2026)

Pracownik zgłasza w aplikacji, że pracuje dłużej niż w grafiku (nadgodziny) albo krócej (np. źle się czuje i wychodzi wcześniej). Kierownik zatwierdza albo odrzuca zgłoszenie i może sam zmienić godziny. Liczą się godziny zatwierdzone.

- Pracownik: przycisk „Zgłoś inne godziny” jest przy dzisiejszej albo trwającej zmianie w „Mój grafik” i przy zmianach z ostatnich 14 dni (zwijana sekcja „Minione zmiany”). Pracownik wpisuje godziny od–do, w których naprawdę pracował albo będzie pracował; przy trwającej zmianie „Wychodzę teraz” wpisuje bieżącą godzinę. Może dopisać powód. Ekran od razu mówi, co to znaczy („Nadgodziny: +1 h”, „Krócej o 2 h”). Zgłoszenie czeka na kierownika. Nowe zgłoszenie tej samej zmiany zastępuje poprzednie, a czekające zgłoszenie pracownik może wycofać.
- Kierownik dostaje powiadomienie i decyduje na ekranie „Godziny” (zgłoszenia czekające na decyzję są na górze, liczba czekających jest w menu): „Zatwierdź” albo „Odrzuć”. Pracownik dostaje powiadomienie o decyzji.
- Kierownik może sam zmienić godziny osoby na dowolnej opublikowanej zmianie swojego lokalu, także po fakcie („Zmień godziny sam” na ekranie „Godziny” i „Zmień godziny” w karcie zmiany opublikowanego grafiku). Zmiana działa od razu, zastępuje czekające zgłoszenie tej zmiany, a pracownik dostaje powiadomienie. Godziny takie jak w grafiku przywracają plan (też sprawdzane, czy nie nachodzą na inną zmianę). Formularz zapisuje godziny tylko osobie, którą kierownik widział: gdy zmianę dostał ktoś inny, zapis się nie udaje. „Zmień godziny sam” ma wybór miesiąca, więc sięga też po starsze zmiany. Plan asystenta ze zmianą godzin nie zapisze się, gdy od jego przygotowania zmieniły się godziny tej zmiany albo przyszło nowe zgłoszenie.
- Liczą się tylko zatwierdzone godziny: ekran „Godziny” i plik CSV (z kolumnami nadgodzin i krótszych zmian), suma godzin w „Mój grafik” i odpowiedzi asystenta. Grafik jako plan się nie zmienia: generator, walidator i oceny liczą godziny z grafiku. Przy zmianie widać godziny naprawdę i godziny z grafiku. Zgłoszenie czekające na decyzję niczego nie liczy.
- Granice: tylko opublikowana zmiana tej osoby; pracownik zgłasza najwyżej 14 dni wstecz (kierownik zmienia godziny bez tej granicy); zmiana trwa najdłużej 24 godziny; godziny nie mogą nachodzić na inną zmianę tej osoby. Koniec przed początkiem to koniec następnego dnia, jak w ustawieniach zmian.
- Gdy zmianę dostaje inna osoba (poprawka grafiku, oddanie zmiany, kierownik zmienia obsadę albo zamienia ludzi), czekające zgłoszenie i zatwierdzone godziny poprzedniej osoby wygasają na stałe, a ta osoba dostaje powiadomienie. Gdy zmiana do niej wróci, liczy się plan; inne godziny kierownik ustawia od nowa (ze sprawdzeniem kolizji). Tak żadna godzina nie liczy się dwa razy (recenzja Piotra z 21.11.2026).
- Zatwierdzone godziny, na które nachodzi zmiana dana tej osobie później, też wygasają z powiadomieniem: przy poprawce grafiku od razu, a przy „Zmień obsadę”, zamianie i oddaniu zmiany taka osoba ma najpierw problem „Zatwierdzone godziny tej osoby nachodzą na tę zmianę” (kierownik może go pominąć, pracownik nie weźmie takiej zmiany).
- „Nadgodziny” w aplikacji i w pliku CSV to godziny ponad grafik, nie nadgodziny w rozumieniu Kodeksu pracy (normy dobowe i tygodniowe). Ekran „Godziny” mówi to pod tabelą, a kolumna CSV nazywa się „Nadgodziny (ponad grafik)” (uwaga z przeglądu Prelint z 21.11.2026).
- Asystent: pracownik może napisać w czacie „zostałem godzinę dłużej” albo „źle się czuję, wyjdę o 13”. Asystent sprawdza jego zmianę i pokazuje gotowe zgłoszenie z przyciskiem „Wyślij kierownikowi”; nic nie wysyła się samo, tak jak przy „Zaznacz „nie mogę””. Kierownik może napisać „Ania wyszła dziś o 12” albo „zatwierdź nadgodziny Kasi”: asystent przygotowuje plan (inne godziny, zatwierdzenie albo odrzucenie zgłoszenia), który działa dopiero po „Zatwierdź zmiany”, także po publikacji grafiku okresu. Zgłoszenia asystent czyta przez API tak jak ekran „Godziny”.

## Asystent odpowiada na wszystko o Grafikomacie i lokalu (decyzja Piotra z 19.11.2026)

Zastępuje decyzję „Zakres asystenta: wyłącznie zasady” z 18.11.2026. Powód: test z 19.11.2026 (pliki `testy-asystenta/` w projekcie) pokazał, że ludzie pytają asystenta o grafik, godziny, dyspozycje i oddane zmiany, a odmowa za każdym razem zniechęca.

- Główna sprawczość asystenta się nie zmienia: kierownikowi zamienia polecenia na zasady z katalogu i polecenia o osobach (nic się nie zapisuje bez „Zatwierdź zmiany”), a pracownikowi zamienia prośby na preferencje dla generatora.
- Poza tym asystent odpowiada na każde pytanie o Grafikomat i lokal (odpowiedź z datami, godzinami lub liczbami mówi, na którym ekranie to sprawdzić; od 22.11.2026 czaty nie mają stałej notki „Asystent może się pomylić”, decyzja Piotra): kiedy i z kim jest zmiana, ile jest godzin, do kiedy zaznaczyć dyspozycje, kto ich jeszcze nie wysłał, jakie są prośby, oddane zmiany, dlaczego zmiana jest bez obsady, jak coś zrobić w aplikacji i gdzie to jest.
- Dane bierze z tego samego API co aplikacja, wyłącznie do odczytu i z prawami osoby, która pisze: pracownik widzi przez asystenta tylko to, co widzi w swoich ekranach (swój grafik z osobami na tej samej zmianie, swoje dyspozycje i prośby, zmiany do wzięcia, swoje powiadomienia); kierownik to, co widzi w swoich lokalach. Numery telefonów nie trafiają do modelu. Notka o danych w czacie pracownika mówi, że asystent kierownika też może czytać jego prośby i dyspozycje.
- Asystent niczego nie zmienia sam poza ścieżkami wyżej (od 20.11.2026 także zgłoszenia godzin, sekcja „Nadgodziny i krótsza zmiana”). Grafiku nie układa, nie publikuje, nie zamienia ludzi, nie wysyła wiadomości i nie zmienia kalendarza: mówi, gdzie w aplikacji to zrobić. Wyjątek dla wygody: gdy pracownik pisze, że w podane dni nie może pracować, a kalendarz tego nie mówi, czat pokazuje przycisk „Zaznacz „nie mogę””; dni zmieniają się dopiero po naciśnięciu, tą samą drogą co w kalendarzu.
- Jedna wiadomość może łączyć pytanie i prośbę albo kilka próśb (do trzech): asystent odpowiada na pytanie i zapisuje prośby, zamiast odrzucać całość. Gdy części prośby nie umie zamienić na ustawienie, mówi to wprost i zostawia ją kierownikowi do przeczytania.
- Pytania niezwiązane z pracą (pogoda, ogólne tematy) dostają krótką, stałą odmowę aplikacji. Polecenia dla asystenta w treści wiadomości lub w danych nie rozszerzają jego uprawnień.
- Pisanie z asystentem nie ma limitów (decyzja Piotra z 20.11.2026): pracownik i kierownik piszą, ile chcą. Nie ma limitu próśb na okres, dziennego limitu wiadomości osoby ani miesięcznego limitu poleceń firmy. Każdy z nich można włączyć z powrotem zmienną środowiskową, bez zmian w kodzie (plan.md). Włączony limit próśb liczy tylko prośby, które się liczą (zrozumiane i zostawione kierownikowi); pytania, odpowiedzi i odrzucone wiadomości go nie zużywają, a przy pełnym limicie asystent dalej odpowiada na pytania i pozwala poprawić istniejącą prośbę.
- Przekazanie wiadomości kierownikowi daje kierownikom lokalu powiadomienie.

## Ustalenia asystenta na okres grafiku (18.11.2026)

Zatwierdzone ustalenia dotyczą jednego okresu zbierania dyspozycji. Domyślnie jest to ostatni nieopublikowany okres, dla którego poproszono o dyspozycje; ekran okresu może otworzyć rozmowę z tym okresem wybranym jawnie. Bez takiego okresu ustalenia czekają bez przypisania. Rozmowa otwarta z okresu, dla którego jeszcze nie poproszono o dyspozycje, również zapisuje do wspólnej kolejki oczekującej; nie wybiera innego aktywnego okresu. „Poproś o dyspozycje” atomowo przejmuje oczekujące ustalenia dla wskazanego okresu. Ponowienie prośby nie przenosi ustaleń z innych okresów.

Publikacja oznacza zestaw jako wykorzystany i usuwa go z domyślnej listy aktywnej, bez kasowania rozmowy, zasad lub poleceń. Regeneracja i korekty tego samego okresu używają jego zachowanego zestawu; nowy okres nie przejmuje wykorzystanych ustaleń. Nieudane generowanie, szkic ani samo rozpoczęcie układania nie zużywają zestawu. Tabela przy dyspozycjach pokazuje zasady i polecenia dla wybranego okresu.

Technicznie `AssistantRuleSet` przechowuje migawkę zasad katalogowych, zmienione kody, lokal, opcjonalny okres oraz datę wykorzystania. Polecenia o osobach i wiadomości wskazują zestaw. Stałe zasady lokalu/grupy pozostają bazą nowych zestawów; rozmowa zmienia wyłącznie zestaw okresu. Migracja zachowuje wcześniejsze polecenia i przypisuje wykorzystane do ostatniej publikacji po ich utworzeniu, a pozostałe do otwartego zbierania dyspozycji lub kolejki oczekującej. Wszystkie zapisy serializują się z publikacją przez blokadę firmy. Zakres firmy, lokalu i wybranego okresu sprawdzany jest na serwerze.

## Decyzje po przeglądzie ustaleń okresowych (18.11.2026)

- **Ustalenia powtarzane w kilku okresach.** Nowy okres zaczyna bez ustaleń; nic nie przechodzi samo. Przy nowym okresie kierownik widzi listę ustaleń z poprzedniego okresu (zasady zmienione w rozmowie i polecenia o osobach) i zaznacza, które skopiować. Domyślnie nic nie jest zaznaczone. Kopia jest osobnym wpisem nowego okresu: późniejsze zmiany nie dotykają okresu źródłowego. Nie są proponowane polecenia o osobach, które odeszły z lokalu, ani takie, których dni już minęły, ani ustalenia już obecne w nowym okresie. Źródłem jest najnowszy wcześniejszy okres lokalu, który ma jakiekolwiek ustalenia.
- **Prośba błędnie odrzucona przez asystenta.** Pracownik może jednym przyciskiem „Przekaż kierownikowi” przekazać oryginalny tekst odrzuconej wiadomości kierownikowi do ręcznej oceny. Samo przekazanie nie włącza prośby do generatora: trafia ona na listę próśb kierownika bez interpretacji, z informacją, że asystent ją odrzucił. Kierownik sam decyduje, czy poprawić grafik ręcznie albo wydać polecenie asystentowi. Przekazane prośby są liczone w raporcie `assistant_misses` (powód `rejected`), co pozwala policzyć błędne odrzucenia.
- To zastępuje wcześniejsze zdania „nie można przekazać bez poprawienia treści” z sekcji o zakresie asystenta.
- „Nie o to mi chodziło” (19.11.2026) najpierw pozwala napisać prośbę inaczej; przekazanie kierownikowi jest drugą możliwością.

## Widok rozmowy z asystentem (18.11.2026)

Asystent kierownika ma własną zakładkę „Asystent” w lokalu. Wiadomości i odpowiedzi tworzą rozmowę, pole pisania jest pod nią, a propozycje zawierają osobne przyciski zatwierdzenia i odrzucenia. Przyjęte lub odrzucone propozycje pozostają w historii. Ostatnie 50 wiadomości danego kierownika w lokalu wraca po odświeżeniu; nie oznacza to rozszerzenia pamięci LLM poza 10 ostatnich wiadomości z tego okresu (od 20.11.2026; wcześniej 6 z 24 godzin). Zapisane polecenia są w bocznym panelu, dostępnym również na telefonie. Ekran zasad prowadzi do rozmowy linkiem.

Wiadomości pracownika w kalendarzu korzystają z tego samego stylu rozmowy i pola pisania. Zachowują dotychczasowy zakres miesiąca/okresu, możliwość edycji i usunięcia oraz przekazania prośby kierownikowi. U kierownika Enter wysyła, Shift+Enter dodaje wiersz. Pod polem pisania nie ma podpowiedzi o klawiszach, oczekiwaniu na odpowiedź ani pamięci asystenta (decyzja Piotra z 20.11.2026); zostaje tylko licznik znaków blisko limitu, a u pracownika jedno zdanie o tym, kto czyta wiadomość. U pracownika Enter zawsze dodaje wiersz, a prośbę wysyła wyłącznie przycisk. Podczas wysyłania nie można wysłać duplikatu. Pracownik pisze prośby dotyczące swoich preferencji, po jednej sprawie. Błędy pozostawiają tekst do poprawy, a nieaktualne odpowiedzi nigdy nie zatwierdzają się same.

Po przeglądzie czatu: limit pamięci (od 20.11.2026: 10 ostatnich zakończonych wiadomości z tego okresu, bez limitu czasu; wcześniej 6 z 24 godzin) jest opisany w „Jak działa asystent”, a starsze wpisy są oznaczone jako archiwum poza pamięcią. Otwarte propozycje wygasają 24 godziny od wysłania polecenia; API odmawia zapisu, historia zostaje, a ponowne przygotowanie wymaga świadomego wysłania treści. Porównanie z grafikiem jest opisane jako pochodzące z chwili przygotowania propozycji. Polecenia o osobach są widoczne także na ekranie zasad, w kolejności ważności. Na telefonie panel ma przycisk z nazwą, a link powrotny i wszystkie zakładki lokalu pozostają widoczne. Prośby pracownika zachowują jawny opis danych czytanych przez Claude (zasada „jedna prośba, jedna sprawa” obowiązywała do 19.11.2026; od tego dnia jedna wiadomość może mieć pytanie i do 3 preferencji); potwierdzenia systemowe nie udają odpowiedzi rozmówcy.

## Wysuwany czat i okienko ustaleń (decyzja Piotra z 18.11.2026)

Zastępuje opis zakładki „Asystent” i rozmowy wbudowanej w kalendarz z sekcji wyżej; zakres asystenta, pamięć, wygasanie propozycji i przypisanie ustaleń do okresu zostają bez zmian.

- Czat asystenta wysuwa się z prawej krawędzi ekranu. Od 22.11.2026 otwiera go przycisk „Asystent” widoczny na każdym ekranie po zalogowaniu (sekcja niżej); pracownik może też użyć „Napisz do asystenta” (bez asystenta: „Napisz prośbę”) w okienku „Twoje prośby” pod kalendarzem. Panel nie zasłania pracy: strona pod nim działa dalej, zamyka go „Zamknij” albo Esc. Na telefonie zajmuje cały ekran.
- Gdy asystent pracuje nad odpowiedzią, w czacie (pracownika i kierownika) jest napis „Myślę…” z małym robotem (Piotr, 22.11.2026: nie „Przygotowuję odpowiedź”); w okienku „Twoje prośby” „Asystent myśli…”.
- Kierownik: zasada lub polecenie trafia do okienka „Ustalenia z asystentem” dopiero po zatwierdzeniu propozycji w rozmowie. Okienko jest w zakładce „Ustalenia” (dawniej „Asystent”), przy dyspozycjach okresu i na ekranie zasad. Kierownik edytuje w nim ustalenia: zmienia kolejność poleceń o osobach, usuwa polecenie, przywraca zasadzie obecne ustawienie lokalu, usuwanie i przywracanie wymagają potwierdzenia, a „Zmień” otwiera czat z gotowym początkiem wiadomości (nic nie wysyła się samo, zmiana wymaga zatwierdzenia nowej propozycji). Po publikacji grafiku okresu ustalenia są tylko do odczytu.
- Pracownik: w okienku „Twoje prośby” są tylko prośby, które się liczą: zrozumiane przez asystenta (trafiają do generatora) albo zostawione kierownikowi do przeczytania. Pracownik może w nim poprawić treść prośby (asystent czyta ją ponownie) albo ją usunąć. Odpowiedzi informacyjne, prośby odrzucone i zastąpione zostają tylko w historii rozmowy. Prośby na stałe z wcześniejszych miesięcy też tam są, z „Zakończ” zamiast poprawiania i usuwania (sekcja „Prośby na stałe”). Wyjątek od 22.11.2026: wiadomość, o którą asystent dopytał i na którą pracownik jeszcze nie odpowiedział, okienko pokazuje osobno jako niezapisaną (sekcja „Asystent pracownika dopytuje”), żeby nie przepadła po cichu.

## Przycisk asystenta na każdym ekranie (decyzja Piotra z 22.11.2026)

Piotr: przycisk asystenta ma być zawsze dostępny, a nie pojawiać się tylko w niektórych miejscach.

- Kierownik: okrągły przycisk z dymkiem w prawym dolnym rogu każdego ekranu panelu (lokale, pracownicy, oddane zmiany, godziny, dostęp i wszystkie zakładki lokalu). Na szerokim ekranie (od 1600 px) ma podpis „Asystent”; węższy zostaje sam ikoną, żeby nie zasłaniać tabel. Przycisk „Asystent” w nagłówku lokalu zostaje obok niego (Piotr: „może być zdublowane”), otwiera czat od razu o tym lokalu. „Ustal w rozmowie” i „Zmień” w okienku ustaleń też zostają, bo otwierają czat na konkretny okres albo z gotowym początkiem wiadomości.
- Czat kierownika dotyczy jednego lokalu: w lokalu tego, który jest na ekranie; poza lokalem ostatniego lokalu, który kierownik otworzył albo wybrał w czacie (Piotr: żeby nie trzeba było ciągle pytać o lokal), a przy jednym lokalu w firmie tego jednego. Gdy lokali jest kilka i żaden nie był jeszcze wybrany, czat najpierw pyta „O którym lokalu rozmawiamy?”. Przy kilku lokalach nad rozmową zawsze jest „Lokal: nazwa” (także w lokalu, bo na telefonie czat zakrywa stronę), a poza lokalem obok „Zmień lokal”. Lokal w archiwum nie ma własnej rozmowy.
- Pracownik: na telefonie „Asystent” (bez asystenta: „Prośby”) to czwarta zakładka w pasku na dole, obok „Mój grafik”, „Kiedy mogę” i „Powiadomienia”, więc niczego nie zasłania. Na komputerze, gdzie zakładki są u góry, ten sam okrągły przycisk jest w prawym dolnym rogu, obok wąskiej kolumny treści. Telefon obrócony poziomo zostawia zakładki u góry strony, tak jak dotąd.
- Czat pracownika dotyczy miesiąca, który jest na ekranie „Kiedy mogę”; na innych ekranach okresu, o który prosi kierownik, a gdy go nie ma, bieżącego miesiąca. Pod tytułem czatu jest „Prośby na grudzień 2026.” (albo dni okresu), żeby prośba napisana z innego ekranu nie trafiła niezauważenie do innego miesiąca. Zamknięcie czatu nie kasuje niewysłanej wiadomości.
- Bez przycisku, gdy firma ma wstrzymany dostęp (tak jak dotąd). Otwarty czat zasłania róg, więc przycisk wtedy znika. Na końcu każdej strony jest miejsce, żeby ostatnie elementy dało się przewinąć spod przycisku, a pasek „Sprawdź i zapisz” na ekranie zasad na telefonie omija róg z przyciskiem.

## Poprawki asystenta po niezależnym QA (18.11.2026)

- Polecenie pracy w danym dniu może wskazywać konkretną zmianę. Zapis, opis i ocena generatora zachowują ten sam zakres. Nieobsługiwanej części odpowiedzi modelu nie wolno po cichu pominąć ani zatwierdzić niepełnego planu.
- Polecenia o osobach i prośby pozostają preferencjami. Potwierdzenie nie obiecuje przydziału ani zmiany dyspozycji w kalendarzu. Zatwierdzenie ustawień nie uruchamia układania grafiku; wyjątek to plan z punktem o ułożeniu, który asystent dodaje tylko na wyraźną prośbę kierownika (sekcja „Inny grafik na prośbę kierownika”, 22.11.2026).
- Funkcja odpowiedzi o danych wróciła 19.11.2026 (sekcja „Asystent odpowiada na wszystko o Grafikomacie i lokalu”), tym razem przez API z prawami osoby, która pisze.
- Kolejne wiadomości kierownika zawierają 10 ostatnich wiadomości tego samego autora w tym lokalu i okresie ustaleń (od 20.11.2026 bez limitu 24 godzin), z informacją, czy plan został przyjęty. Korekta pracownika może zastąpić jedną wcześniejszą prośbę tego pracownika w tym samym okresie lub miesiącu. Stara treść pozostaje w historii jako zastąpiona; nie bierze udziału w układaniu grafiku. Niejasna lub nieaktualna korekta trafia do kierownika bez nowej interpretacji. Decyzja i ważność nadane przez kierownika przechodzą na poprawioną prośbę.
- Interfejs informuje o zakresie danych czytanych przez zewnętrzny asystent. LLM nie publikuje, sam nie układa grafiku (z czatu układanie rusza dopiero po zatwierdzeniu planu, sekcja „Inny grafik na prośbę kierownika”), nie wysyła wiadomości i nie edytuje kalendarza.
- Historyczną odpowiedź informacyjną pracownik może przekazać kierownikowi. Nową prośbę odrzuconą jako poza zakresem może przekazać kierownikowi do ręcznej oceny; nie trafia ona przez to do generatora.
- Historyczne odpowiedzi informacyjne są oznaczone jako odpowiedzi asystenta. Opisy zmian do zatwierdzenia nadal powstają ze sprawdzonej struktury.

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

Firma -> grupa lokali (opcjonalna) -> lokal. Jeden menedżer może prowadzić wiele lokali; jego podstawowym ekranem jest widok zbiorczy grupy. Pracownik ma jeden lokal główny i może pracować także w innych lokalach tej samej firmy (decyzja Piotra z 19.11.2026, zmienia decyzję z 12.11.2026): kierownik drugiego lokalu zaprasza ten sam numer, a po akceptacji lokal dochodzi do lokali dodatkowych tej osoby. Dyspozycje i godziny są wspólne dla wszystkich lokali osoby; generator każdego z jej lokali może ją układać. Praca w lokalu, w którym osoby nie ma na liście, to nadal wyjątek (wzięcie oddanej zmiany, pożyczenie przez menedżera). Jedno konto na numer telefonu w całym systemie; przynależność do firmy i lokalu wynika z przyjętych zaproszeń. Dane firm są od siebie odizolowane: każdy wiersz ma firmę, a każde zapytanie jest nią ograniczone.

## Pracownik (najpierw telefon)

1. Mój grafik: data, lokal, godziny, stanowisko; kto jest ze mną na zmianie.
2. Dyspozycyjność wyłącznie ręcznie w kalendarzu, bez LLM. W kalendarzu są trzy stany: nie mogę / mogę / chętnie. Każdy dzień jest od początku "mogę" (jasna zieleń), "chętnie" to pełniejsza zieleń, więc nie ma pustych, białych dni (decyzja Piotra z 13.11.2026 po testach: biały dzień po "wyczyść" był mylący). "Wolę nie" i "obojętnie" są usunięte (decyzja Piotra z 13.11.2026: takie życzenia pracownik pisze jako prośbę tekstem, np. "wolałbym mieć wolne 5 grudnia", a LLM zamienia ją na typ wolne_dni). Zaznaczanie "pędzlem" (decyzja Piotra z 12.11.2026): pracownik wybiera na dole ekranu stan (nie mogę, mogę albo chętnie), który zaznacza, a potem stuka w dzień albo przeciąga po kilku dniach naraz; nie trzeba pamiętać kolejności stanów. Zapis automatyczny. Przycisków "Cofnij" i "Więcej opcji" nie ma (decyzja Piotra z 13.11.2026 po testach: każdy kolejny przycisk zmniejsza czytelność, a dzień poprawia się jednym stuknięciem). Stuknięcie w dzień, który ma już wybrany stan, albo narzędzie "Godziny dnia" otwiera ten dzień; pod kalendarzem jest lista dni z godzinami z przyciskiem "Zmień". Można tam wybrać godziny (prośba Piotra z 12.11.2026: pracownicy są elastyczni i zaznaczają godziny, w których mogą): przy "chętnie" i "mogę" znaczą "mogę tylko w tych godzinach" (zmiana spoza nich tego dnia liczy się jak "nie mogę"), przy "nie mogę" znaczą "nie w tych godzinach"; koniec przed początkiem to godziny do rana następnego dnia (nocka). Dzień może mieć dwa przedziały godzin (prośba Piotra z 15.11.2026), np. "mogę 6–10 i 16–22": przy "lub" pracownik może dostać zmianę w każdym z nich, przy "albo" najwyżej jedną zmianę tego dnia, w jednym z przedziałów (twarde, jak "nie mogę"); przy "nie mogę" oba przedziały znaczą "nie w tych godzinach". Kalendarz jest zawsze otwarty (decyzja Piotra z 13.11.2026 po testach): pracownik zaznacza dostępność miesiącami na przyszłość, także zanim kierownik o nią poprosi; zamknięte są tylko dni, które minęły, i dni z ułożonym już grafikiem. Gdy kierownik poprosi o dyspozycje na okres, pracownik widzi termin zgłoszenia i przycisk "Wyślij kierownikowi". Po terminie pracownik nadal może poprawiać dyspozycje, aż kierownik ułoży grafik; dni zmienione po terminie kierownik widzi w siatce ze znakiem "po terminie" (decyzja Piotra z 12.11.2026, zamiast twardego zamknięcia).
3. Prośby tekstem tylko dla spraw spoza kalendarza, np. "nie chcę zmiany z osobą X". Pracownik widzi, jak system zrozumiał prośbę, i może poprawić. Spośród ludzi prośby widzi tylko menedżer. Gdy asystent jest włączony, treść prośby czyta też zewnętrzna usługa AI (model językowy, od 21.11.2026 przez OpenRouter), a ekran prośby mówi o tym pracownikowi wprost. Prośbę można napisać zawsze, na każdy miesiąc w kalendarzu, także zanim kierownik poprosi o dyspozycje (decyzja Piotra z 15.11.2026: "żeby zawsze dało się pisać o rzeczach na przyszłość"). Taka prośba należy do miesiąca i dotyczy osoby, nie jednego lokalu: kierownik każdego lokalu, w którym ta osoba pracuje, widzi ją w każdym okresie grafiku, który obejmuje ten miesiąc, a generator bierze z niej tylko dni z danego okresu. Od 22.11.2026 prośba może też obowiązywać na stałe, we wszystkich kolejnych okresach, aż ktoś ją zakończy (sekcja „Prośby na stałe”).
4. Po publikacji pracownik widzi tylko swój grafik na najbliższy okres i sumę godzin (od 22.11.2026 z wypłatą brutto, sekcja „Oczekiwana wypłata”). Nie widzi, czy jego prośby zostały spełnione, ani powodów.
5. Oddanie zmiany: "oddaj zmianę" -> powiadomienie w aplikacji dla osób ze wszystkich lokali firmy, które zaznaczyły wtedy dyspozycyjność, mają właściwe stanowisko i nie złamią twardych reguł -> "biorę" -> menedżer zatwierdza. Zapisuj historię przypisań zmiany, żeby później łatwo dodać zamiany zmian między dwiema osobami. Do zatwierdzenia zmiana należy do osoby, która ją oddaje. Po zatwierdzeniu zmiana od razu przechodzi w opublikowanym grafiku (bez nowej wersji: ślad zostaje w historii przypisań, z osobą, która zatwierdziła), jest przypięta, żeby ponowne układanie nie cofnęło uzgodnienia, a wszyscy zainteresowani dostają powiadomienie. Kierownik może w "Zasadach" lokalu włączyć "Przejęcie oddanej zmiany bez zatwierdzania" (domyślnie wyłączone): wtedy pierwsza osoba, która weźmie zmianę i dla której walidator nie znajduje nowego twardego problemu, dostaje ją od razu, a oddający, biorący i kierownicy lokalu dostają powiadomienie (decyzja Piotra 15.11.2026). Kierownik może też zarządzać tym sam w "Oddane zmiany" (decyzja Piotra 18.11.2026): wybrać dowolną osobę na oddawaną zmianę, zakończyć oddawanie (zmiana zostaje u oddającego), poszukać chętnych na zmianę pracownika w jego imieniu, a w opublikowanym grafiku wpisać inną osobę na dowolną zmianę albo zamienić dwie osoby zmianami (ten sam lokal i okres). Walidator sprawdza każdą taką zmianę i pokazuje zastrzeżenia, ale kierownik może je pominąć ("Wpisz mimo to", "Zamień mimo to"). Działa to też dla zmian, które już się zaczęły albo minęły, żeby godziny zgadzały się z tym, kto naprawdę pracował. Zainteresowani dostają powiadomienie, a ślad zostaje w historii przypisań. W „Mój grafik” zmiany do wzięcia są w zwijanej sekcji „Zmiany do wzięcia”, zwiniętej na start, z liczbą zmian w nagłówku (prośba Piotra z 22.11.2026: lista zajmowała za dużo miejsca).
6. Powiadomienia tylko w aplikacji (zakładka "Powiadomienia" z licznikiem nowych): prośba o dyspozycje, nowy lub poprawiony grafik, zmiana do wzięcia, decyzja kierownika o oddanej zmianie. Kierownik widzi chętnych do wzięcia zmian w "Oddane zmiany" z licznikiem w nagłówku.

## Menedżer (najpierw komputer)

1. Dane lokalu w formularzach: stanowiska, typy zmian z godzinami (stałe lub dowolne, także przez północ), obsada według stanowisk dla dnia tygodnia i typu zmiany, a inna obsada wybranego dnia w kalendarzu (kierownik wybiera dzień i ustawia liczbę osób na zmianę i stanowisko; prośba Piotra z 18.11.2026 zamiast listy wyjątków) albo wprost w edycji grafiku przez "Dodaj miejsce" i "Usuń miejsce" przy zmianie, dni zamknięcia lokalu (cały dzień bez obsady, np. święto; prośba Piotra z 15.11.2026 po audycie), okres grafiku (tydzień lub miesiąc), termin dyspozycji, pracownicy (stanowiska, stopień doświadczenia, osobiste maksimum i cel godzin). Aplikacja niczego z tego nie zakłada z góry.
   Dla każdego dnia tygodnia, stanowiska i typu zmiany kierownik osobno ustawia liczbę osób, liczbę doświadczonych i godziny zmiany z dowolnymi godzinami. Może też skopiować ustawienia poniedziałku na cały tydzień.
   Stopień doświadczenia (decyzja Piotra z 13.11.2026): kierownik daje każdej osobie na liście pracowników jedną z trzech etykiet: początkujący, samodzielny (domyślna) albo doświadczony. Pracownik nigdy nie widzi swojego stopnia. Generator używa go w zasadzie "Początkujący z doświadczonymi", żeby na zmianie nie było wielu niedoświadczonych osób naraz. Pomysł na później: podpowiedź stopnia z przepracowanych godzin (kierownik zatwierdza jednym przyciskiem; nigdy samoczynnie).
   Decyzja Piotra z 13.11.2026 po przeglądzie konkurencji (raport: https://claude.ai/artifact/PyE6iDjvz9cUqPWGqXnL8c): (a) stopień można ustawić osobno dla stanowiska: stopień osoby jest domyślny, a przy osobie z kilkoma stanowiskami kierownik może wskazać inny stopień na wybranym stanowisku (ktoś doświadczony przy piecu bywa początkujący na kasie); (b) w obsadzie obok liczby osób kierownik może wpisać, ile z nich ma być doświadczonych ("zamknięcie: 2 osoby, w tym 1 doświadczona"). To twardy wymóg jak stanowisko: generator nie postawi na takim miejscu mniej doświadczonej osoby (woli zostawić lukę), a oddanie zmiany pracownikowi, który go łamie, jest odrzucane. Kierownik może go złamać ręczną zmianą i tak opublikować grafik; widzi wtedy ostrzeżenie (decyzja Piotra z 19.11.2026, wcześniej taka zmiana była odrzucana); (c) zasada "Początkujący z doświadczonymi" zostaje i liczy stopień na stanowisku danej zmiany; (d) opiekun dla nowej osoby ("stawiaj Olę tylko z Marią", "Ola nie liczy się do obsady") to polecenie do asystenta w etapie 10, bez osobnego ekranu; (e) etykiet uprawnień z datą ważności (np. książeczka sanepidu) na razie nie budujemy. Decyzja Piotra z 15.11.2026: zanim kierownik ułoży grafik, aplikacja ostrzega, gdy na którymś stanowisku obsada wymaga na jednej zmianie więcej doświadczonych osób, niż lokal ich ma. To tylko ostrzeżenie: grafik nadal można ułożyć, a takie miejsca zostaną wolne.
2. Przegląd dyspozycji: siatka pracownicy x dni, lista próśb z interpretacją (menedżer może prośbę odrzucić albo oznaczyć jako ważniejszą lub mniej ważną), lista osób bez zgłoszonej dyspozycji.
3. Lokal dziedziczy ustawienia i kolejność zasad grupy. Zmiana samego miejsca zasady na liście tworzy lokalne ustawienie. Przywrócenie zasady grupy odtwarza jej wartości i miejsce. Zasady lokalu: gotowa lista z przełącznikami i licznikami; kolejność na liście = ważność; każdą zasadę można oznaczyć "bez wyjątków" (twarda). Przed zapisaniem pokaż skutek zmiany na danych z ostatniego okresu, np. "przez tę zasadę 6 próśb nie zostałoby spełnionych".
4. Generowanie grafiku osobno dla każdego lokalu (lokale są od siebie niezależne: każdy ma własne zasady i wagi; "ułóż dla wszystkich" uruchamia osobne generowanie dla każdego lokalu); osoba pracująca w kilku lokalach jest w puli każdego z nich, a zmiany, które już ma w opublikowanych grafikach i najnowszych szkicach innych lokali, są dla niej zajęte i liczą się do jej godzin, odpoczynku i dni z rzędu). Lokale zależą od siebie tylko wtedy, gdy kierownik tak powie w poleceniu dla asystenta. Wynik z oceną i wyjaśnieniami; ręczna edycja (przeciąganie, przypinanie) z walidacją na żywo przez endpoint; publikacja z wersjami. Gdy kierownik ręcznie wpisuje osobę, która ma w tym czasie inną zmianę (w tym samym grafiku albo w grafiku lub szkicu innego lokalu), aplikacja pyta, czy na pewno chce to zmienić; po potwierdzeniu zdejmuje osobę z tamtej zmiany, która zostaje pusta, a przy opublikowanym grafiku innego lokalu daje znać tej osobie i kierownikowi tamtego lokalu. Zmianę w lokalu, którego kierownik nie prowadzi, albo taką, która już się zaczęła, zmienia tylko jej kierownik (decyzja Piotra z 18.11.2026). Dwie zmiany jednej osoby w tym samym czasie nadal nie mogą zostać zapisane.
5. Ponowne generowanie układa od nowa wszystko poza zmianami przypiętymi i dniami, które minęły: nieprzypięte ręczne poprawki znikają. Kierownik, który chce coś zmienić w wyniku, pisze polecenie dla asystenta (LLM), a ten zamienia je na zasady i ich ważność. Wyraźnie inny grafik daje „Ułóż inaczej” albo prośba w czacie (sekcja „Inny grafik na prośbę kierownika”, 22.11.2026). Układanie w trakcie (w kolejce albo już liczone) kierownik może anulować przyciskiem "Anuluj": nic się nie zapisuje, a wcześniejszy szkic zostaje (prośba Piotra z 13.11.2026 po testach).
6. Okres grafiku: kierownik wpisuje daty okresu i dzień, w którym będzie układał grafik. Może jednym przyciskiem poprosić wszystkich pracowników lokalu o dyspozycje (powiadomienie w aplikacji z okresem i terminem). Widzi, kto już wpisał dyspozycje, a kto nie, i może przypomnieć tylko tym, którzy jeszcze nie wpisali.
   Grafik powstaje wyłącznie na świadome polecenie kierownika, gdy minie termin albo gdy wszyscy wpiszą dyspozycje (Piotr, 12.11.2026: ludzie zwlekają do ostatniej chwili, więc grafik ma sens dopiero przy komplecie danych). Aplikacja nie układa grafiku sama, okresowo ani automatycznie; może jedynie podpowiedzieć, że przyszła pora.
7. Podsumowanie godzin w miesiącu z podziałem na lokale i wypłatą brutto (od 22.11.2026, sekcja „Oczekiwana wypłata”), eksport CSV.
8. Usuwanie (prośba Piotra z 18.11.2026): kierownik może usunąć każdą rzecz, którą dodał, a historia grafików i godzin zostaje.
   - Osoba: "Usuń z lokalu" w formularzu pracownika (obok wyłączenia z grafiku), po potwierdzeniu. Osoba bez żadnej zmiany w grafikach znika całkiem. Osoba ze zmianami w zapisanych grafikach znika z list i traci dostęp do firmy, ale jej dawne zmiany i godziny zostają; wraca tylko przez nowe zaproszenie. Kierownik usunięty z listy pracowników dalej jest kierownikiem.
   - Stanowisko: zawsze da się usunąć. Gdy jest w zapisanym grafiku, znika z ustawień, obsady i od ludzi, a dawne grafiki dalej pokazują jego nazwę.
   - Grupa lokali (właściciel): lokale zostają bez grupy i zachowują zasady grupy jako własne.
   - Lokal (właściciel): usunąć można tylko lokal bez pracowników i bez okresów grafiku (dodany przez pomyłkę); lokal, który działał, przenosi się do archiwum.
   - Okres grafiku: można usunąć, dopóki grafik nie był opublikowany (np. złe daty); znika ze szkicami i prośbami pracowników na ten okres, dyspozycje w kalendarzu zostają.
   - Szkic grafiku (prośba Piotra z 22.11.2026): czerwona ikona kosza ("Usuń szkic") przy szkicu w zakładce "Grafik", po potwierdzeniu, bo tego nie da się cofnąć. Znika wersja, którą kierownik właśnie ogląda (bieżący szkic albo starsza nieopublikowana wersja wybrana w "Wersje"), z ręcznymi poprawkami i przypięciami (poprawka 22.11.2026: wcześniej znikały też starsze szkice). Usunięcie starszej wersji nie zmienia bieżącego grafiku. Po usunięciu bieżącego szkicu bieżąca jest znów wersja sprzed niego: wcześniejszy szkic (np. sprzed "Ułóż od nowa") wraca do edycji, a przy poprawkach opublikowanego grafiku wraca on sam. Gdy nie zostaje żadna wersja, okres wraca do zbierania dyspozycji (pracownicy znów mogą je zmieniać, "Ułóż grafik" działa jak przed pierwszym układaniem). Wersji, która była kiedyś opublikowana, nie da się usunąć. Bieżącego szkicu nie da się usunąć w trakcie układania (najpierw "Anuluj"). Okno potwierdzenia mówi, która wersja wraca, i że obsada dni oraz zmiany w grafikach innych lokali (zdjęcie osoby po potwierdzonym konflikcie) zostają.
   - Powiadomienie: każdy usuwa swoje krzyżykiem albo wszystkie naraz (działa też w trybie tylko do odczytu).

## Reguły (bez typu umowy)

Decyzja Piotra z 13.11.2026: aplikacja nie zna typu umowy i nie wbudowuje ograniczeń umowy o pracę ani Kodeksu pracy. Nie ingeruje w to; kierownik sam ustawia wszystko w zasadach lokalu i może pisać prośby tekstem (np. "doświadczony kelner zawsze z niedoświadczonym").
- Zawsze twarde są tylko: "nie mogę", właściwe stanowisko, brak nakładających się zmian, zmiany przypięte ręcznie, dni, które minęły, i zasady kierownika oznaczone "bez wyjątków". Wymóg "w tym doświadczonych" z obsady generator spełnia zawsze, ale kierownik może go złamać ręczną zmianą i tak opublikować grafik (ostrzeżenie zamiast blokady; decyzja Piotra z 19.11.2026: kierownik ma władzę absolutną).
- Twarde reguły wiążą generator, nie kierownika (decyzja Piotra z 18.11.2026: "kierownik ma władzę absolutną i Grafikomat nie powinien mu nic blokować"). Przy ręcznej edycji kierownik może wpisać osobę mimo "nie mogę" albo zasady "bez wyjątków": aplikacja pokazuje powód i pyta raz "Zapisać mimo to?". Taka zmiana jest oznaczona "wpisane mimo przeszkód", przypięta (ponowne układanie jej nie cofa) i nie blokuje publikacji. Nie da się tylko wpisać osoby bez właściwego stanowiska (stanowisko dodaje się w "Pracownicy"). Dwie zmiany jednej osoby w tym samym czasie nie zostają w grafiku: aplikacja pyta "Na pewno chcesz to zmienić?" i po potwierdzeniu zdejmuje osobę z tamtej zmiany, także w innym lokalu (decyzja Piotra z 18.11.2026). Jeśli zmiana łamie też "nie mogę" albo zasadę, jedno potwierdzenie obejmuje oba.
- Kierownik może poprawiać także dni, które minęły (decyzja Piotra z 18.11.2026: gdy ktoś zamieni się w ostatniej chwili poza aplikacją, grafik trzeba poprawić, żeby godziny były policzone tak, jak było naprawdę). Poprawka przeszłości idzie tą samą drogą co każda inna ("Popraw grafik" -> szkic -> "Opublikuj") i jest przypięta sama. Generator nadal nie zmienia dni, które minęły. Ekran "Godziny" mówi kierownikowi, że zamianę poza aplikacją poprawia w grafiku i publikuje, a godziny się przeliczą (zamiast dawnego "to plan, a nie ewidencja").
- Przy ręcznej edycji kierownik wybiera osobę (z listy albo łapiąc jej kafelek) i siatka pokazuje jej dyspozycje na każdej zmianie jej stanowiska: zielono "chętnie" (pełna zieleń) i "może" (jasna zieleń), żółto "nie może" ("nie mogę", które kierownik może wpisać mimo to, albo inna zmiana w tym czasie, której nie da się obejść). Kolory i znaki są te same co w kalendarzu pracownika.
- Osobiste maksimum godzin to zasada "bez wyjątków" z zapasem w procentach, domyślnie 10% (decyzja Piotra z 15.11.2026 po audycie: osoba z maksimum 180 h może dostać najwyżej 198 h); kierownik może zmienić zapas (0–50%) albo zrobić z niej zwykłą zasadę. Cel godzin jest miękki, chyba że kierownik oznaczy go "bez wyjątków".
- Zasady dobrej praktyki: miękkie, włączone domyślnie, kierownik może każdą wyłączyć albo zamienić na twardą: min. 11 h między zmianami, max 6 dni pracy z rzędu, równy podział weekendów i zmian zamykających. Na ekranie zasad nie mają osobnego znacznika (decyzja Piotra z 20.11.2026).
- Zasady czasu pracy w katalogu: "Godziny pracy w ciągu dnia" (domyślnie najwyżej 8 h) i "Wolne w tygodniu" (domyślnie co najmniej 35 h bez przerwy). Decyzja Piotra z 13.11.2026: są dobrą praktyką, czyli włączone jako miękkie w nowych i istniejących lokalach; kierownik może je wyłączyć albo oznaczyć "bez wyjątków". Dotyczą wszystkich osób lokalu. Odpoczynek dobowy to zasada "Odpoczynek między zmianami".
- Odpowiedzialność za zgodność grafiku z prawem pracy spoczywa na kierowniku; aplikacja tego nie sprawdza.

## Generator (najważniejsza część)

a) OR-Tools CP-SAT uruchamiany w workerze, nigdy w zapytaniu HTTP. Limit czasu na uruchomienie (np. 30 s), zwracamy najlepszy znaleziony wynik. Najwyżej 1-2 zadania solvera naraz w kolejce.
b) Cel: najpierw minimalizuj liczbę nieobsadzonych slotów, potem sumę kar za złamane miękkie zasady. Zasady menedżera ważą wobec próśb pracowników jak 80 do 20 (wartość w profilu wag lokalu lub grupy, niewidoczna w interfejsie). Gdy ludzi brakuje, grafik i tak powstaje, z wyraźnie zaznaczonymi dziurami.
c) Pierwsza wersja: 1 wariant. Zaprojektuj kod tak, żeby później dodać 3 warianty (proporcje 70/30, 80/20, 90/10, min. 15% różnych przypisań). Ten sam mechanizm różnicy (bez dodatkowych dziur, potem jak najbliżej progu, potem kara) daje od 22.11.2026 „Ułóż inaczej” z progiem 30%.
d) Ocena pokazywana menedżerowi to trzy osobne wartości, liczone tym samym wzorem dla każdego wariantu: liczba nieobsadzonych slotów, ocena "zasady menedżera" w % (zasady lokalu, zasady dobrej praktyki, cel godzin) i ocena "prośby pracowników" w % ("chętnie" z kalendarza oraz prośby tekstem). Ocena grupy = 100 * (1 - suma(w_i * v_i) / suma(w_i)), gdzie v_i to stopień naruszenia 0-1. Grafik z dziurami jest oznaczony jako niekompletny i nie może wyglądać na dobry.
e) Niezależny walidator w Pythonie (osobny od solvera, pytest z przypadkami granicznymi) sprawdza każdy wariant i ma ostatnie słowo. Ten sam walidator obsługuje endpoint walidacji przy ręcznej edycji.
f) Stabilność: przy ponownym generowaniu w trakcie okresu kara za każdą zmianę względem opublikowanego grafiku, żeby jedna nieobecność nie przetasowała całego miesiąca. Dni, które minęły, są zamrożone.
g) Wyjaśnienia: szybkie sprawdzenie bezpośrednich przyczyn (dyspozycyjność, limit godzin, odpoczynek, stanowisko) bez ponownego uruchamiania solvera dla każdej prośby. Głębsza analiza tylko na żądanie menedżera.
h) Kierownik dostosowuje generator poleceniami tekstem do asystenta (LLM): zasady, ich ważność i poprawki wyniku; asystent zamienia polecenie na ustawienia z zamkniętych list i sam nigdy nie układa grafiku (układa go generator; z czatu rusza tylko po zatwierdzeniu planu z punktem o ułożeniu). Docelowo wszystko ma być ustawialne poleceniem. Polecenie daje plan, który kierownik widzi prostymi zdaniami (ułożonymi przez aplikację, nie przez model) razem ze skutkiem na ostatnim grafiku; nic się nie zmienia, dopóki kierownik planu nie zatwierdzi. Plan może: włączyć, wyłączyć, ustawić i przesunąć zasadę z katalogu, oznaczyć ją "bez wyjątków", dodać albo usunąć polecenie o konkretnej osobie (dwie osoby osobno lub razem, osoba tylko na danej zmianie lub bez niej, limit godzin, wolne w daty lub dni tygodnia, praca w daty lub dni tygodnia z liczbą dni, z których wystarczy część, i liczbą zmian danego dnia), a na wyraźną prośbę kierownika także ułożyć grafik okresu od nowa albo inaczej po zatwierdzeniu (sekcja „Inny grafik na prośbę kierownika”). W poleceniu kierownika i prośbie pracownika limit godzin osoby może dotyczyć całego okresu albo każdego tygodnia od poniedziałku do niedzieli. Wspólna zmiana oznacza ten sam lokal, typ zmiany i godziny. W starszych wpisach jednoznaczny limit tygodniowy jest oznaczony informacją o zmianie sposobu liczenia. Przydział w grafiku kierownika pokazuje podstawę wpisu i wpływ zamiany na zasady i prośby. Polecenia o osobach liczą się razem z zasadami kierownika (nie z prośbami pracowników) i mają własną kolejność.
i) Prośby pracowników LLM zamienia na strukturę: typ z zamkniętej listy (unikaj_osoby, preferuj_osobe, typ_zmiany, limit_godzin, limit_zmian, wolne_dni, chce_pracowac, inne; unikaj_osoby i preferuj_osobe mogą dotyczyć tylko jednej zmiany, np. "nie stawiajcie mnie z Zuzanną na zamknięciu" = nie razem na zmianie, która zamyka lokal, a gdzie indziej mogą pracować razem; limit_zmian = "najwyżej 3 nocki w tygodniu": najwyżej tyle zmian (danego rodzaju albo wszystkich) dziennie, w każdym tygodniu albo w okresie, dodane 20.11.2026 po teście Piotra; wolne_dni = "wolę nie pracować w te dni lub dni tygodnia", miękko, bo twarde "nie mogę" zaznacza się w kalendarzu; chce_pracowac = "chcę pracować w te dni", z liczbą dni, z których wystarczy część ("albo 12, albo 13" = jeden z nich), i liczbą zmian danego dnia ("dwie zmiany pod rząd"), dodane 15.11.2026 po teście Piotra), kogo dotyczy, daty, dni tygodnia, poziom (bardzo_wazne / wazne / mile_widziane), pewność 0-1, opis jednym zdaniem. Do LLM wysyłaj tylko treść prośby, okres grafiku, nazwy zmian i imiona z danego lokalu (nazwisko skrócone do litery tylko przy takich samych imionach). Od 19.11.2026 asystent może też sam odczytać przez API to, co pracownik widzi w aplikacji (sekcja „Asystent odpowiada na wszystko o Grafikomacie i lokalu”). Bez klucza API (zmienna OPENROUTER_API_KEY albo ANTHROPIC_API_KEY), przy typie "inne" albo gdy odpowiedź wskazuje dzień spoza okresu, prośba trafia do menedżera bez interpretacji. Od 22.11.2026 asystent przy niepewnym dniu, osobie, zmianie lub zakresie najpierw dopytuje pracownika, najwyżej trzy razy z rzędu (decyzja Piotra z 22.11.2026; sekcja „Asystent pracownika dopytuje”); przy niskiej pewności (poniżej 0,6) i przy osobie lub zmianie spoza lokalu pyta sama aplikacja. Do menedżera trafia to, czego po ostatniej odpowiedzi nadal nie da się zapisać (wcześniej niska pewność i osoba lub zmiana spoza lokalu szły do menedżera od razu). Kierownik widzi przy niej powód: asystent był wyłączony, nie był pewny albo wystąpił błąd. Prośbę, która przyszła przy wyłączonym asystencie albo przy błędzie, kierownik może jednym przyciskiem dać asystentowi do przeczytania, gdy asystent już działa. Pracownik widzi, jak prośba została zrozumiana, i może powiedzieć "nie o to mi chodziło" (wtedy czyta ją kierownik).
j) "Wszystko bardzo ważne" (problem zgłoszony przez Piotra) jest niemożliwe z konstrukcji, w trzech miejscach:
   - Kierownik nie ma poziomów ważności. Ważność to wyłącznie miejsce na liście (zasad i poleceń o osobach), a każda pozycja ma inne miejsce: podniesienie jednej rzeczy zawsze obniża inne. Asystent nie może nadać poziomu, musi wybrać miejsce i napisać, co przez to spadnie niżej.
   - "Bez wyjątków" jest osobnym, świadomym wyborem (jedyny wyjątek ustawiony z góry to osobiste maksimum godzin z zapasem, decyzja Piotra z 15.11.2026, patrz wyżej): asystent ustawia je tylko na wyraźne "nigdy", plan pokazuje skutek na ostatnim grafiku, a od trzeciej takiej zasady aplikacja ostrzega, że mogą zostać zmiany bez obsady.
   - Pracownik: poziom nadaje LLM na podstawie powodu, nie wykrzykników, a wszystkie prośby jednej osoby w okresie dzielą wspólny budżet wagi (tyle, co jedna "bardzo ważna" i jedna "ważna"). Kto oznaczy pięć rzeczy jako bardzo ważne, rozkłada ten sam głos na pięć próśb. Tak samo oznaczenie przez kierownika wszystkich próśb jako "ważniejsza" nic nie zmienia, bo ocena jest względna.

## Logowanie i zaproszenia

- Wyłącznie kod SMS, bez haseł, Google i e-maila. Tożsamość to numer +48 (normalizacja biblioteką phonenumbers). Kod 6 cyfr, ważny 5 minut, max 5 prób; sesja ok. 60 dni.
- Kody wysyłamy tylko na numery +48, które mają konto albo oczekujące zaproszenie, oraz przy rejestracji nowego menedżera. Limity: kilka kodów na numer na godzinę i limit na adres IP.
- Lokalnie kod wypisywany w konsoli. Prawdziwa bramka SMS (np. SMSAPI.pl) za wymienialnym interfejsem, dopiero przy wdrożeniu.
- Menedżer zaprasza pracownika po numerze telefonu: wiersz w tabeli invitations ze statusem (oczekuje / przyjęte / odrzucone / anulowane), unikalne oczekujące zaproszenie na parę (placówka, numer). SMS z zaproszeniem NIE jest wysyłany. Pracownik po zalogowaniu widzi zaproszenie: Akceptuj / Odrzuć; akceptacja w jednej transakcji. Kto ma już konto, widzi nowe zaproszenie od razu.
- Limity dokładnie: kolejny kod najwcześniej po 60 s, najwyżej 5 kodów na numer na godzinę i 20 próśb o kod z jednego adresu IP na godzinę (liczą się też prośby dla nieznanych numerów). Nowy kod unieważnia poprzedni. W bazie jest tylko skrót kodu.
- Nieznany numer przy logowaniu dostaje jasną odpowiedź ("Nie znamy tego numeru. Poproś kierownika o zaproszenie…"), a nie udawane wysłanie kodu: dla osób niechętnych technologii czekanie na SMS, który nie przyjdzie, jest gorsze niż ryzyko, że ktoś sprawdzi, czy numer ma konto (to ryzyko ogranicza limit na adres IP).
- Zapraszając, menedżer może od razu wpisać imię i nazwisko; trafiają na konto przy akceptacji, jeśli konto nie ma jeszcze imienia. Wiele osób naraz zaprasza z wklejonej listy albo pliku (sekcja „Zapraszanie wielu osób naraz” na początku); takie zaproszenie może mieć stanowiska, które osoba dostaje po akceptacji. Pracownika zaprasza menedżer lokalu, menedżera zaprasza tylko właściciel firmy. Akceptacja zaproszenia pracownika tworzy członkostwo w firmie i profil pracownika z tym lokalem jako głównym. Osoba, która już pracuje w firmie, po akceptacji zaproszenia do kolejnego lokalu dostaje go jako lokal dodatkowy (lokal główny się nie zmienia). Kierownik lokalu dodatkowego ustawia jej stanowiska w swoim lokalu; stopień, godziny i wyłączenie z grafiku są wspólne i ustawia je kierownik lokalu głównego.
- Kierownik, który sam pracuje na zmianach, dodaje siebie do grafiku lokalu jednym przyciskiem w zakładce "Pracownicy" (bez zaproszenia); dostaje wszystkie stanowiska lokalu i może je potem zawęzić (prośba Piotra z 13.11.2026).
- Zmiana numeru telefonu: robi ją superadmin w panelu. Konto, członkostwa i historia zostają; wszystkie sesje tego konta wygasają i trzeba zalogować się nowym numerem. Zaproszenia oczekujące na stary numer menedżer wysyła ponownie. Numery spoza Polski: poza prototypem.
- Poza kodami logowania nic nie wysyłamy SMS-em ani e-mailem. Powiadomienia tylko w aplikacji.

## Dostęp i subskrypcja (bez płatności online, bez Stripe)

- Kody na darmową subskrypcję generuje superadmin w panelu admina Django: długość dostępu 30 albo 60 dni, maksymalna liczba użyć (domyślnie 1), opcjonalna data ważności samego kodu, notatka (np. nazwa firmy).
- Kod losowy, min. 10 znaków bez mylących znaków (0/O, 1/l), wielkość liter bez znaczenia; limit prób wpisania.
- Kod wpisuje kierownik przy zakładaniu firmy albo później w ustawieniach. Subskrypcja dotyczy całej firmy; pracownicy niczego nie wpisują.
- Tabela subscriptions niezależna od dostawcy płatności: firma, status (aktywna / wygasła), data końca, źródło ("kod", w przyszłości "stripe"). Kolejny kod przedłuża dostęp od daty końca, nie od dnia wpisania.
- 7 dni przed końcem baner w panelu kierownika. Po wygaśnięciu tryb tylko do odczytu: grafik widoczny, bez edycji i generowania. Danych nie usuwamy.
- Firma założona bez kodu dostaje 30 dni okresu próbnego z pełnym dostępem (decyzja Piotra z 12.11.2026; 13.11.2026 wydłużone z 14 do 30 dni, żeby zmieścił się pełny miesięczny cykl: dyspozycje, termin, ułożenie, publikacja). Okres próbny dostaje tylko pierwsza firma zakładana przez daną osobę. Po okresie próbnym firma jest tylko do odczytu, dopóki kierownik nie wpisze kodu; kod wpisany w okresie próbnym dolicza swoje dni do końca okresu próbnego, więc nic nie przepada.
- W trybie tylko do odczytu każda zmiana danych firmy jest odrzucana (HTTP 402 z komunikatem po polsku); wyjątki: wpisanie kodu, odpowiedź zaproszonej osoby na zaproszenie oraz oznaczenie i usunięcie własnych powiadomień (pracownik nadal widzi grafik i powiadomienia; oddawać ani brać zmian nie można).
- Limit prób wpisania kodu: 5 błędnych na konto i 20 na adres IP w ciągu godziny. Kod ma 12 znaków, pokazywany w grupach po 4 (ABCD-EFGH-JKMN); spacje i myślniki nie mają znaczenia. Jeden kod można użyć w danej firmie tylko raz. Kody widać w całości tylko raz, zaraz po wygenerowaniu; w bazie jest skrót i pierwsze 4 znaki.
- Układanie grafiku nie ma limitu na firmę ani na miesiąc (Piotr, 22.11.2026: najpierw domyślnie wyłączony, tego samego dnia „w ogóle usuń ten limit”; wcześniej roboczo 30 na miesiąc). Aplikacja nie liczy ułożeń i nie pokazuje ich kierownikowi; superadmin widzi liczbę układań i minuty solvera w zestawieniu kosztów (z `GenerationRun`).

## Stos

- Backend w całości w Pythonie: Django + Django Ninja (OpenAPI), PostgreSQL, migracje Django, sesje Django + własny moduł logowania kodem SMS.
- Kolejka: Procrastinate na Postgresie (bez Redisa i RabbitMQ), osobny proces worker z tego samego kodu. Zapis danych i dodanie zadania do kolejki w jednej transakcji.
- Frontend w TypeScripcie, bez Next.js: React + Vite (SPA), TanStack Router + TanStack Query, Tailwind + shadcn/ui, React Hook Form + Zod, dnd-kit. Klient API generowany z OpenAPI (orval).
- Docker Compose: Django, worker, Postgres, Caddy. Caddy serwuje frontend i przekazuje /api do Django pod jedną domeną. Na razie uruchamiane lokalnie; wdrożenie na jeden serwer VPS ma być później jednym krokiem.

## UX i wygląd

- Zanim powstanie pierwszy ekran, przygotuj plik z kierunkiem wizualnym i tokenami (kolory, typografia, odstępy, promienie, rozmiary dotyku) i zaczekaj na moją akceptację. Zaakceptowany 12.11.2026 kierunek "kartka z zaplecza": spokojne chłodne tło jak papier, jeden niebieski akcent jak z długopisu, kratka tylko tam, gdzie się zaznacza, najbliższa zmiana jak kartka z kalendarza zdzieraka; krój Atkinson Hyperlegible Next. Tokeny: `frontend/src/styles/tokens.css`. Wszystkie ekrany korzystają wyłącznie z tych tokenów. Komponenty shadcn/ui są ostylowane tokenami, nie zostają w wyglądzie domyślnym.
- Bez generycznego wyglądu: żadnych fioletowych gradientów, szklanych efektów, emoji jako ikon, kart w kartach ani pulpitu pełnego kafelków ze statystykami. Jeden kolor akcentu, krój pisma z charakterem i dobrą czytelnością polskich znaków, spokojne tło.
- Pracownik ma dwa ekrany: "Mój grafik" i "Kiedy mogę". Elementy dotykowe min. 44 px na ekranie dotykowym (36 px przy myszce; zmniejszone 18.11.2026 na prośbę Piotra, wcześniej 48 px), tekst podstawowy 16 px (wcześniej 18 px; treść, główne przyciski, nawigacja i nagłówek; 14 px tylko dla podpisów pomocniczych pod tytułem lub przyciskiem oraz etykiet czterech stanów w pasku pędzla, które muszą się zmieścić obok siebie na telefonie 360 px; 13 px tylko dla nazw dni tygodnia nad kalendarzem, etykiet tygodni i godzin w kafelku dnia, które widać też w pełnym rozmiarze w liście „Dni z godzinami”), wysoki kontrast, zwykłe słowa, brak ukrytych gestów, każdą pomyłkę da się poprawić od ręki (dzień zmienia się jednym stuknięciem, bez osobnego przycisku "Cofnij"), natychmiastowa reakcja na dotknięcie.
- Stany dyspozycyjności odróżnia nie tylko kolor, ale też ikona lub wzór i podpis.
- Każdy ekran ma zaprojektowany stan pusty, stan ładowania i stan błędu, z tekstami w ludzkim języku.
- Dane przykładowe i teksty mają być prawdziwe: polskie imiona, realne godziny zmian, realne stanowiska.
- Po każdym etapie z ekranami dołącz do pull requesta zrzuty ekranu w szerokości telefonu i komputera.

## Dane przykładowe

Firma z 4 piekarniami w jednej grupie i jednym menedżerem, 15-25 pracowników na lokal, dyspozycyjność na kolejny miesiąc, 20-30 próśb tekstem i kilka zasad menedżera, w tym sprzeczne ze sobą. Druga, osobna firma do sprawdzenia izolacji danych.

## Poza pierwszą wersją

Trzy warianty grafiku, zamiany zmian proponowane przez pracowników, wnioski urlopowe, zadania na zmianie, koszt pracy w układaniu grafiku (wypłata z godzin jest od 22.11.2026), dodatek za święto, rejestracja czasu pracy (poza zgłaszaniem innych godzin zmiany, od 20.11.2026), miesięczne zestawienie przepracowanych godzin zleceniobiorców, płatności, aplikacje iOS i Android, wysyłka SMS przez bramkę.

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
