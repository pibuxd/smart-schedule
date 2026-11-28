import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/router.dart';
import 'package:grafikomat/session/prefs.dart';
import 'package:grafikomat/ui/sheet.dart';
import 'package:material_ui/material_ui.dart';

import '../helpers.dart';

// The website's `MyScheduleScreen.test.tsx`, case by case.

const shift = <String, Object?>{
  'id': 'a1',
  'date': '2026-11-13',
  'start_at': '2026-11-13T06:00:00+01:00',
  'end_at': '2026-11-13T14:00:00+01:00',
  'start_time': '06:00',
  'end_time': '14:00',
  'hours': 8,
  'location_name': 'Wieliczka – Rynek',
  'position_name': 'Sprzedawca',
  'shift_type_name': 'Ranna',
  'away': false,
  'coworkers': ['Anna Wróbel', 'Marek Zając'],
};

const offer = <String, Object?>{
  'id': 'o1',
  'shift': {
    'date': '2026-11-20',
    'start_time': '14:00',
    'end_time': '22:00',
    'hours': 8,
    'location_id': 'l2',
    'location_name': 'Bochnia',
    'position_name': 'Sprzedawca',
    'shift_type_name': 'Popołudniowa',
  },
  'offered_by_name': 'Ola Kos',
  'away': true,
  'my_claim_id': null,
  'my_claim_status': null,
};

final dayBefore = DateTime(2026, 11, 12);
final shiftStart = DateTime.parse(shift['start_at']! as String);
final shiftEnd = DateTime.parse(shift['end_at']! as String);

Map<String, Object?> withShift(Map<String, Object?> changes) => {...shift, ...changes};

FakeServer server({
  List<Object?> shifts = const [shift],
  List<Object?>? recent,
  List<Object?> offers = const [],
  Map<String, Object?> told = const {'notified': 3, 'notified_here': 1},
}) {
  return FakeServer()
    ..on('GET /api/me', (_) => Reply(200, meJson()))
    ..on('GET /api/me/offers', (_) => Reply(200, offers))
    ..on('GET /api/me/schedule', (_) => Reply(200, scheduleJson(shifts: shifts, recent: recent)))
    ..on('POST /api/me/shifts/a1/offer', (_) => Reply(201, {'id': 'o9', 'status': 'open', 'at_once': false, ...told}))
    ..on(
      'POST /api/offers/o9/cancel',
      (_) => const Reply(200, {'id': 'o9', 'status': 'cancelled', 'notified': 0, 'notified_here': 0, 'at_once': false}),
    )
    ..on(
      'POST /api/offers/o1/claim',
      (_) => Reply(201, {...offer, 'my_claim_id': 'c1', 'my_claim_status': 'pending', 'at_once': false}),
    )
    ..on('POST /api/me/hours-changes', (_) => const Reply(201, hoursChange))
    ..on('POST /api/hours-changes/h1/cancel', (_) => const Reply(200, hoursChange));
}

const hoursChange = <String, Object?>{
  'id': 'h9',
  'status': 'pending',
  'employee_id': 'e1',
  'employee_name': 'Ola Nowak',
  'location_id': 'l1',
  'location_name': 'Wieliczka – Rynek',
  'date': '2026-11-13',
  'position_name': 'Sprzedawca',
  'planned_start_time': '06:00',
  'planned_end_time': '14:00',
  'planned_hours': 8,
  'start_time': '06:00',
  'end_time': '11:15',
  'hours': 5.25,
  'difference_minutes': -165,
  'reason': '',
  'by_manager': false,
  'created_at': '2026-11-13T10:15:00Z',
  'decided_at': null,
  'decided_by_name': '',
  'assignment_id': 'a1',
};

Future<ProviderContainer> open(
  WidgetTester tester,
  FakeServer server, {
  required DateTime Function() clock,
  String? link,
  bool readOnly = false,
}) async {
  if (readOnly) {
    server.on(
      'GET /api/me',
      (_) => Reply(
        200,
        meJson(
          companies: [
            {'id': 'c1', 'name': 'Piekarnia Pod Lipą', 'role': 'employee', 'read_only': true, 'works_shifts': true},
          ],
        ),
      ),
    );
  }
  final container = await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'}, clock: clock);
  if (link != null) {
    container.read(routerProvider).go(link);
    await settle(tester);
  }
  return container;
}

Future<void> tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pump();
  await tester.tap(finder);
  await settle(tester);
}

Finder outlined(Finder inside) =>
    find.ancestor(of: inside, matching: find.byWidgetPredicate((w) => w is FocusOutline && w.focused));

Finder rich(String text) => find.textContaining(text, findRichText: true);

void main() {
  testWidgets('shows the next shift as a big calendar page and the month total', (tester) async {
    await open(tester, server(), clock: () => dayBefore);
    expect(find.text('Najbliższa zmiana'), findsOneWidget);
    expect(find.text('jutro'), findsOneWidget);
    expect(find.text('13'), findsOneWidget);
    expect(find.text('6:00–14:00'), findsOneWidget);
    expect(find.text('Z Tobą: Anna Wróbel, Marek Zając'), findsOneWidget);
    expect(find.text('Razem w listopadzie'), findsOneWidget);
    expect(find.text('112 godz.'), findsOneWidget);
    expect(find.text('Wypłata brutto'), findsNothing);
  });

  testWidgets('outlines the shift of a tapped notification and opens the shift to take it is about', (tester) async {
    final later = withShift({'id': 'a2', 'date': '2026-11-16', 'start_at': '2026-11-16T06:00:00+01:00'});
    await open(
      tester,
      server(shifts: [shift, later], offers: [offer]),
      clock: () => dayBefore,
      link: '/grafik?dzien=2026-11-13&oferta=o1',
    );
    expect(outlined(find.text('Najbliższa zmiana')), findsOneWidget);
    // "Zmiany do wzięcia" is open by itself, with the offer outlined.
    expect(outlined(find.text('Weź zmianę')), findsOneWidget);
  });

  testWidgets("opens today's shift that has ended, not tomorrow's, when its hours were approved", (tester) async {
    final ended = withShift({'id': 'p1', 'can_report': true});
    final tomorrow = withShift({
      'id': 'a2',
      'date': '2026-11-14',
      'start_at': '2026-11-14T06:00:00+01:00',
      'end_at': '2026-11-14T14:00:00+01:00',
    });
    await open(
      tester,
      server(shifts: [tomorrow], recent: [ended]),
      clock: () => DateTime.parse('2026-11-13T15:00:00+01:00'),
      link: '/grafik?dzien=2026-11-13',
    );
    expect(outlined(find.text('Najbliższa zmiana')), findsNothing);
    // "Minione zmiany" is open, with that shift outlined.
    expect(outlined(find.text('Inne godziny')), findsOneWidget);
  });

  testWidgets('shows the pay under the hours only when the manager set rates', (tester) async {
    final s = server()
      ..on(
        'GET /api/me/schedule',
        (_) => Reply(
          200,
          scheduleJson(
            shifts: [shift],
            months: [
              {'month': '2026-11', 'hours': 112, 'pay': 3516.8, 'supplements_pay': 36, 'unpriced_hours': 0},
              {'month': '2026-12', 'hours': 40, 'pay': 251.2, 'supplements_pay': 0, 'unpriced_hours': 32},
              {'month': '2027-01', 'hours': 16, 'pay': null, 'unpriced_hours': 16},
            ],
          ),
        ),
      );
    await open(tester, s, clock: () => dayBefore);
    // January has no rates at all: no pay line.
    expect(find.text('Wypłata brutto'), findsNWidgets(2));
    expect(find.text('3516,80 zł'), findsOneWidget);
    expect(find.text('251,20 zł'), findsOneWidget);
    expect(find.text('Bez 32 godz., bo kierownik nie ustawił dla nich stawki.'), findsOneWidget);
    // November only: December has no supplements.
    expect(find.text('W tym dodatki: 36,00 zł.'), findsOneWidget);
    expect(rich('szacun'), findsNothing);
  });

  testWidgets('keeps an ongoing shift visible without offering it', (tester) async {
    await open(tester, server(), clock: () => shiftStart);
    expect(find.text('Trwa Twoja zmiana'), findsOneWidget);
    expect(find.text('Oddaj tę zmianę'), findsNothing);
  });

  testWidgets('skips an ended shift and says there is none ahead', (tester) async {
    await open(tester, server(), clock: () => shiftEnd);
    expect(find.text('Nie masz jeszcze zmian w grafiku'), findsOneWidget);
    expect(find.text('112 godz.'), findsOneWidget);
  });

  testWidgets('gives a shift away after explaining that it stays mine until the manager decides', (tester) async {
    final s = server();
    await open(tester, s, clock: () => dayBefore);
    await tap(tester, find.text('Oddaj tę zmianę'));
    expect(find.text('Oddać tę zmianę?'), findsOneWidget);
    expect(find.text('Dopóki kierownik nie zdecyduje, to nadal Twoja zmiana.'), findsOneWidget);
    await tap(tester, find.text('Oddaj zmianę'));
    expect(rich('Daliśmy znać 3 osobom: 1 z Twojego lokalu i 2 z innych lokali firmy'), findsOneWidget);
    expect(s.sent('POST /api/me/shifts/a1/offer'), hasLength(1));
  });

  testWidgets('tells in the right words that one person can take the shift', (tester) async {
    await open(tester, server(told: {'notified': 1, 'notified_here': 1}), clock: () => dayBefore);
    await tap(tester, find.text('Oddaj tę zmianę'));
    await tap(tester, find.text('Oddaj zmianę'));
    expect(rich('Daliśmy znać jednej osobie z Twojego lokalu, która może wziąć tę zmianę.'), findsOneWidget);
  });

  testWidgets('shows a shift being given away and lets me keep it', (tester) async {
    final s = server(
      shifts: [
        withShift({'offer_id': 'o9', 'offer_status': 'claimed'}),
      ],
    );
    await open(tester, s, clock: () => dayBefore);
    await tap(tester, find.text('Oddajesz: czeka na kierownika'));
    expect(find.text('Ktoś chce wziąć tę zmianę. Teraz decyduje kierownik.'), findsOneWidget);
    await tap(tester, find.text('Jednak nie oddaję'));
    expect(s.sent('POST /api/offers/o9/cancel'), hasLength(1));
  });

  testWidgets('folds shifts to take under a heading that says how many there are', (tester) async {
    final pending = {...offer, 'id': 'o2', 'my_claim_id': 'c2', 'my_claim_status': 'pending'};
    await open(tester, server(offers: [offer, pending]), clock: () => dayBefore);
    expect(rich('2 zmiany · czeka na kierownika: 1'), findsOneWidget);
    expect(find.text('Weź zmianę'), findsNothing);
    await tap(tester, rich('Zmiany do wzięcia'));
    expect(find.text('Weź zmianę'), findsOneWidget);
    expect(find.text('Zgłoszone. Kierownik musi to zatwierdzić. Damy Ci znać.'), findsOneWidget);
  });

  testWidgets('lists shifts to take and asks for one', (tester) async {
    final s = server(offers: [offer]);
    await open(tester, s, clock: () => dayBefore);
    await tap(tester, rich('Zmiany do wzięcia'));
    expect(find.text('Bochnia (inny lokal). Oddaje: Ola Kos'), findsOneWidget);
    await tap(tester, find.text('Weź zmianę'));
    expect(s.sent('POST /api/offers/o1/claim'), isEmpty); // one more tap first
    await tap(tester, find.text('Tak, zgłoś mnie'));
    expect(s.sent('POST /api/offers/o1/claim'), hasLength(1));
  });

  testWidgets('takes a shift at once when the location hands shifts over without approval', (tester) async {
    var taken = false;
    final s = server()
      ..on(
        'GET /api/me/offers',
        (_) => Reply(
          200,
          taken
              ? []
              : [
                  {...offer, 'at_once': true},
                ],
        ),
      )
      ..on('POST /api/offers/o1/claim', (_) {
        taken = true;
        return Reply(201, {...offer, 'my_claim_id': 'c1', 'my_claim_status': 'approved', 'at_once': true});
      });
    await open(tester, s, clock: () => dayBefore);
    await tap(tester, rich('Zmiany do wzięcia'));
    await tap(tester, find.text('Weź zmianę'));
    expect(rich('Od razu będzie Twoja'), findsOneWidget);
    await tap(tester, find.text('Tak, biorę'));
    expect(find.text('Zmiana jest Twoja.'), findsOneWidget);
  });

  testWidgets('says the first taker gets my shift when the location needs no approval', (tester) async {
    await open(
      tester,
      server(
        shifts: [
          withShift({'handover_at_once': true}),
        ],
      ),
      clock: () => dayBefore,
    );
    await tap(tester, find.text('Oddaj tę zmianę'));
    expect(rich('Pierwsza osoba, która ją weźmie, dostaje ją od razu'), findsOneWidget);
    expect(find.text('Dopóki nikt jej nie weźmie, to nadal Twoja zmiana.'), findsOneWidget);
  });

  testWidgets('hides giving away in read-only mode', (tester) async {
    await open(tester, server(), clock: () => dayBefore, readOnly: true);
    expect(find.text('Najbliższa zmiana'), findsOneWidget);
    expect(find.text('Oddaj tę zmianę'), findsNothing);
  });

  testWidgets('explains an empty schedule and points to "Kiedy mogę"', (tester) async {
    await open(tester, server(shifts: []), clock: () => dayBefore);
    expect(find.text('Nie masz jeszcze zmian w grafiku'), findsOneWidget);
    await tap(tester, find.text('Zaznacz, kiedy możesz pracować'));
    expect(find.text('Kiedy mogę'), findsWidgets);
    expect(rich('Tu zaznaczysz, kiedy możesz pracować'), findsOneWidget);
  });

  testWidgets('says which schedule the manager is still arranging', (tester) async {
    final s = server()
      ..on(
        'GET /api/me/schedule',
        (_) => Reply(
          200,
          scheduleJson(
            shifts: [shift],
            publishedUntil: '2026-11-30',
            preparing: [
              {'location_name': 'Wieliczka – Rynek', 'start': '2026-12-01', 'end': '2026-12-31'},
              {'location_name': 'Bochnia', 'start': '2026-12-07', 'end': '2026-12-13'},
            ],
          ),
        ),
      );
    await open(tester, s, clock: () => dayBefore);
    expect(
      find.text(
        'Grafik od 1 grudnia i od 7 grudnia w lokalu Bochnia jest w przygotowaniu. Zobaczysz tu swoje zmiany, '
        'gdy kierownik go opublikuje.',
      ),
      findsOneWidget,
    );
    expect(find.text('Grafik jest opublikowany do poniedziałku 30 listopada.'), findsOneWidget);
    expect(find.text('Kolejne dni'), findsOneWidget);
    expect(find.text('Wolne'), findsWidgets);
  });

  testWidgets('shows a plain error with a retry button', (tester) async {
    final s = server()..on('GET /api/me/schedule', (_) => const Reply(500, {}));
    await open(tester, s, clock: () => dayBefore);
    expect(rich('To błąd po naszej stronie'), findsOneWidget);
    expect(find.text('Spróbuj jeszcze raz'), findsOneWidget);
  });

  group('other hours', () {
    testWidgets('reports leaving a running shift early with "Wychodzę teraz"', (tester) async {
      var now = shiftStart.add(const Duration(hours: 5));
      final s = server(
        shifts: [
          withShift({'can_report': true}),
        ],
      );
      await open(tester, s, clock: () => now);
      await tap(tester, find.text('Zgłoś inne godziny'));
      expect(find.text('To te same godziny, które liczą się teraz.'), findsOneWidget);
      // The screen was opened at 11:00; the tap comes at 11:15 by the location's clock.
      now = shiftStart.add(const Duration(hours: 5, minutes: 15));
      await tap(tester, find.text('Wychodzę teraz'));
      await tester.enterText(find.widgetWithText(TextField, 'Powód (nie musisz pisać)'), 'źle się czuję');
      await settle(tester);
      expect(find.text('Krócej o 2 h 45 min'), findsOneWidget);
      await tap(tester, find.text('Wyślij kierownikowi'));
      expect(rich('Wysłane. Kierownik zatwierdzi albo odrzuci te godziny'), findsOneWidget);
      expect(s.sent('POST /api/me/hours-changes').single.body, {
        'assignment_id': 'a1',
        'start_time': '06:00',
        'end_time': '11:15',
        'reason': 'źle się czuję',
      });
    });

    testWidgets('says what overtime means while typing the hours', (tester) async {
      await open(
        tester,
        server(
          shifts: [
            withShift({'can_report': true}),
          ],
        ),
        clock: () => shiftStart.subtract(const Duration(hours: 1)),
      );
      await tap(tester, find.text('Zgłoś inne godziny'));
      expect(find.text('Wychodzę teraz'), findsNothing); // not started yet
      await tester.enterText(find.widgetWithText(TextField, 'Do'), '1530');
      await settle(tester);
      expect(find.text('15:30'), findsOneWidget);
      expect(find.text('Nadgodziny: +1 h 30 min'), findsOneWidget);
    });

    testWidgets('shows approved hours, a waiting report and lets me take the report back', (tester) async {
      final s = server(
        shifts: [
          withShift({
            'can_report': true,
            'worked': {
              'start_at': shift['start_at'],
              'end_at': '2026-11-13T15:00:00+01:00',
              'start_time': '06:00',
              'end_time': '15:00',
              'hours': 9,
              'difference_minutes': 60,
              'by_manager': false,
            },
            'report': {
              'id': 'h1',
              'start_time': '06:00',
              'end_time': '16:00',
              'hours': 10,
              'difference_minutes': 120,
              'reason': '',
            },
          }),
        ],
      );
      await open(tester, s, clock: () => shiftStart);
      expect(find.text('6:00–15:00'), findsOneWidget);
      expect(find.text('W grafiku 6:00–14:00, nadgodziny: +1 h (zatwierdzone)'), findsOneWidget);
      expect(find.text('Zgłoszone 6:00–16:00: czeka na kierownika'), findsOneWidget);
      await tap(tester, find.text('Zgłoszone inne godziny: zmień albo wycofaj'));
      expect(rich('Czeka na kierownika: 6:00–16:00 (nadgodziny: +2 h)'), findsOneWidget);
      await tap(tester, find.text('Wycofaj zgłoszenie'));
      expect(s.sent('POST /api/hours-changes/h1/cancel'), hasLength(1));
    });

    testWidgets('offers other hours for past shifts and not for a shift next week', (tester) async {
      final later = withShift({
        'id': 'a2',
        'date': '2026-11-20',
        'start_at': '2026-11-20T06:00:00+01:00',
        'end_at': '2026-11-20T14:00:00+01:00',
        'can_report': true,
      });
      final past = withShift({
        'id': 'a0',
        'date': '2026-11-10',
        'start_at': '2026-11-10T06:00:00+01:00',
        'end_at': '2026-11-10T14:00:00+01:00',
        'can_report': true,
      });
      await open(
        tester,
        server(shifts: [later], recent: [past]),
        clock: () => dayBefore,
      );
      expect(find.text('Zgłoś inne godziny'), findsNothing);
      await tap(tester, rich('Minione zmiany'));
      await tap(tester, find.text('Inne godziny'));
      expect(find.text('wtorek 10 listopada, w grafiku 6:00–14:00, Sprzedawca'), findsOneWidget);
    });

    testWidgets('moves a shift that just ended to the past shifts, with other hours at hand', (tester) async {
      await open(
        tester,
        server(
          shifts: [
            withShift({'can_report': true}),
          ],
        ),
        clock: () => shiftEnd,
      );
      await tap(tester, rich('Minione zmiany'));
      await tap(tester, find.text('Inne godziny'));
      expect(rich('w grafiku 6:00–14:00'), findsOneWidget);
    });

    testWidgets('hides reporting in read-only mode', (tester) async {
      await open(
        tester,
        server(
          shifts: [
            withShift({'can_report': true}),
          ],
        ),
        clock: () => shiftStart,
        readOnly: true,
      );
      expect(find.text('Trwa Twoja zmiana'), findsOneWidget);
      expect(find.text('Zgłoś inne godziny'), findsNothing);
    });
  });
}
