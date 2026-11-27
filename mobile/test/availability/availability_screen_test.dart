import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/router.dart';
import 'package:grafikomat/session/prefs.dart';
import 'package:material_ui/material_ui.dart';

import 'package:grafikomat/features/availability/availability_screen.dart';

import '../helpers.dart';

// The website's `AvailabilityScreen.test.tsx`, `AvailabilityCalendar.test.tsx` and `DayHoursSheet.test.tsx`, case by
// case. "Twoje prośby" under the calendar is tested with the chat in `test/requests/requests_test.dart`.

const period = <String, Object?>{
  'id': 'p1',
  'location_name': 'Wieliczka – Rynek',
  'start': '2026-12-01',
  'end': '2026-12-31',
  'status': 'collecting',
  'deadline': '2099-11-24',
  'editable': true,
  'assistant_reads': false,
};

final today = DateTime(2026, 11, 13);

const nightDay = <String, Object?>{
  'date': '2026-12-04',
  'state': 'prefer',
  'from_time': '22:00:00',
  'to_time': '06:00:00',
};

/// The two reads of the screen (the asked period, then one month of the calendar) and every write. The test server
/// answers for December whatever month is asked; enough for one screen.
FakeServer server({
  Map<String, Object?>? asked = period,
  String? submittedAt,
  List<String> locked = const [],
  List<String> unpublished = const [],
  List<Object?> days = const [nightDay],
  List<String> locationNames = const ['Rynek'],
  bool readOnly = false,
}) {
  return FakeServer()
    ..on(
      'GET /api/me',
      (_) => Reply(
        200,
        meJson(
          companies: [
            {'id': 'c1', 'name': 'Piekarnia Pod Lipą', 'role': 'employee', 'read_only': readOnly, 'works_shifts': true},
          ],
        ),
      ),
    )
    ..on('GET /api/me/availability', (_) => Reply(200, {'period': asked, 'days': [], 'submitted_at': submittedAt}))
    ..on(
      'GET /api/me/calendar',
      (_) => Reply(200, {
        'start': '2026-12-01',
        'end': '2026-12-31',
        'days': days,
        'locked': locked,
        'unpublished': unpublished,
        'period': asked,
        'submitted_at': submittedAt,
        'location_names': locationNames,
      }),
    )
    ..on('PUT /api/me/calendar', (_) => const Reply(204))
    ..on(
      'POST /api/me/availability/submit',
      (_) => Reply(200, {'period': asked, 'days': [], 'submitted_at': '2026-11-13T09:00:00Z'}),
    );
}

/// "Kiedy mogę" on a phone-sized screen (the bar of states at the bottom shows its line of help there).
Future<ProviderContainer> open(WidgetTester tester, FakeServer server, {String link = '/kiedy-moge'}) async {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final container = await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'}, clock: () => today);
  container.read(routerProvider).go(link);
  await settle(tester);
  return container;
}

/// A calendar day by what a screen reader says about it.
Finder day(String label) => find.byWidgetPredicate((w) => w is Semantics && w.properties.label == label);

/// Inside the sheet that slid up (the bar at the bottom has the same three states).
Finder inSheet(Finder finder) => find.descendant(of: find.byType(BottomSheet), matching: finder);

/// One of the three states in the bar at the bottom.
Finder tool(String label) => find.descendant(of: find.byType(StateBar), matching: find.text(label));

Future<void> tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pump();
  await tester.tap(finder);
  await settle(tester);
}

/// Picks a time from the "Od"/"Do" list ([which] counts the fields with that label, top first).
Future<void> pickTime(WidgetTester tester, String label, String time, {int which = 0}) async {
  final field = find.ancestor(of: find.text(label), matching: find.byType(DropdownButtonFormField<String>)).at(which);
  final current = tester.widget<DropdownButtonFormField<String>>(field).initialValue!;
  await tap(tester, field);
  // The list opens on the chosen time; earlier times are above it.
  final earlier = time.padLeft(5, '0').compareTo(current) < 0;
  await tester.scrollUntilVisible(find.text(time), earlier ? -150 : 150, scrollable: find.byType(Scrollable).last);
  await tester.ensureVisible(find.text(time).last);
  await tester.pumpAndSettle();
  await tester.tap(find.text(time).last);
  await settle(tester);
}

Finder rich(String text) => find.textContaining(text, findRichText: true);

List<Map<String, Object?>> written(FakeServer server) => [
  for (final sent in server.sent('PUT /api/me/calendar'))
    for (final day in ((sent.body! as Map)['days'] as List)) Map<String, Object?>.from(day as Map),
];

void main() {
  testWidgets('is open for marking ahead when the manager has not asked yet', (tester) async {
    final api = server(asked: null, days: []);
    await open(tester, api);
    expect(rich('Zaznacz, kiedy możesz pracować w kolejnych miesiącach'), findsOneWidget);
    expect(find.text('Listopad 2026'), findsOneWidget);
    expect(find.text('Wybierz, a potem zaznacz dni:'), findsOneWidget);
    expect(find.text('Wyślij kierownikowi'), findsNothing);
    await tap(tester, find.byTooltip('Następny miesiąc'));
    expect(find.text('Grudzień 2026'), findsOneWidget);
    final reads = api.sent('GET /api/me/calendar').toList();
    expect(reads, hasLength(2));
    expect(reads.last.query, {'company_id': 'c1', 'start': '2026-12-01', 'end': '2026-12-31'});
  });

  testWidgets('opens on the month a notification links to, but not beyond what the calendar reaches', (tester) async {
    await open(tester, server(), link: '/kiedy-moge?miesiac=2027-01');
    expect(find.text('Styczeń 2027'), findsOneWidget);
    await open(tester, server(), link: '/kiedy-moge?miesiac=2026-01');
    expect(find.text('Grudzień 2026'), findsOneWidget); // the asked period
  });

  testWidgets('opens a later month from a notification when its period is open, even past the usual reach', (
    tester,
  ) async {
    // Tests of PR #82 (26.11.2026): with December still open, a link about March opened December.
    final march = {...period, 'id': 'p3', 'start': '2027-03-01', 'end': '2027-03-31'};
    final api = server()
      ..on('GET /api/me/calendar', (sent) {
        final start = sent.query['start']!;
        final inMarch = start == '2027-03-01';
        return Reply(200, {
          'start': inMarch ? '2027-03-01' : '2026-12-01',
          'end': inMarch ? '2027-03-31' : '2026-12-31',
          'days': [],
          'locked': [],
          'unpublished': [],
          'period': inMarch ? march : (start == '2027-04-01' ? null : period),
          'submitted_at': null,
          'location_names': ['Rynek'],
        });
      });
    await open(tester, api, link: '/kiedy-moge?miesiac=2027-03');
    expect(find.text('Marzec 2027'), findsOneWidget);
    expect(rich('Zaznacz, kiedy możesz pracować w marcu'), findsOneWidget);
    final forward = tester.widget<IconButton>(
      find.ancestor(of: find.byTooltip('Następny miesiąc'), matching: find.byType(IconButton)),
    );
    expect(forward.onPressed, isNull);
    expect(api.sent('GET /api/me/calendar').any((s) => s.query['start'] == '2027-03-01'), isTrue);
    // April has no open period, so its link falls back to the period the manager asked about.
    await open(tester, api, link: '/kiedy-moge?miesiac=2027-04');
    expect(find.text('Grudzień 2026'), findsOneWidget);
  });

  testWidgets('opens on the period the manager asked about and shows the deadline', (tester) async {
    await open(tester, server());
    expect(find.text('Grudzień 2026'), findsOneWidget);
    expect(rich('Zaznacz, kiedy możesz pracować w grudniu. Masz czas do wtorku 24 listopada'), findsOneWidget);
    expect(find.text('Wyślij kierownikowi'), findsOneWidget);
  });

  testWidgets('sends the marks to the manager and says when', (tester) async {
    final api = server();
    await open(tester, api);
    await tap(tester, find.text('Wyślij kierownikowi'));
    expect(api.sent('POST /api/me/availability/submit').single.body, {'company_id': 'c1', 'period_id': 'p1'});
    expect(rich('Wysłane do kierownika 13 listopada'), findsOneWidget);
    expect(find.text('Wyślij kierownikowi'), findsNothing);
  });

  testWidgets('does not let days with an arranged schedule be changed', (tester) async {
    final api = server(locked: ['2026-12-01', '2026-12-02']);
    await open(tester, api);
    await tap(tester, day('wtorek 1 grudnia: mogę, nie da się zmienić'));
    expect(day('wtorek 1 grudnia: mogę, nie da się zmienić'), findsOneWidget);
    expect(api.sent('PUT /api/me/calendar'), isEmpty);
    expect(rich('Na szare dni grafik jest już opublikowany'), findsOneWidget);
  });

  testWidgets('says when the locked days are still being arranged, not published', (tester) async {
    // Piotr, 23.11.2026: "Kiedy mogę" said December was arranged while "Mój grafik" showed nothing of it.
    await open(tester, server(locked: ['2026-12-01', '2026-12-02'], unpublished: ['2026-12-01', '2026-12-02']));
    expect(rich('Grafik na szare dni jest w przygotowaniu'), findsOneWidget);
    expect(rich('gdy kierownik go opublikuje'), findsOneWidget);
    expect(rich('grafik jest już opublikowany'), findsNothing);
  });

  testWidgets('says that availability is shared when the person works in several locations', (tester) async {
    await open(tester, server(locationNames: ['Rynek', 'Dworcowa']));
    expect(rich('Pracujesz w kilku lokalach (Rynek, Dworcowa). Dyspozycje są wspólne'), findsOneWidget);
  });

  testWidgets('shows states with words for screen readers, including night hours', (tester) async {
    await open(tester, server());
    final night = day('piątek 4 grudnia: chętnie, tylko 22:00–06:00 (do rana)');
    expect(night, findsOneWidget);
    expect(find.descendant(of: night, matching: find.text('22–6')), findsOneWidget);
    expect(day('wtorek 1 grudnia: mogę'), findsOneWidget);
    expect(find.text('Dni z godzinami'), findsOneWidget);
  });

  testWidgets('marks a day with the chosen state and saves it', (tester) async {
    final api = server();
    await open(tester, api);
    await tap(tester, tool('Nie mogę'));
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    expect(day('wtorek 1 grudnia: nie mogę'), findsOneWidget);
    expect(written(api), [
      {'date': '2026-12-01', 'state': 'cannot', 'one_shift': false},
    ]);
    expect(find.text('Zapisane'), findsOneWidget);
    expect(find.text('Cofnij'), findsNothing);
  });

  testWidgets('lets a finger scroll: sliding over days marks nothing', (tester) async {
    final api = server();
    await open(tester, api);
    await tester.drag(day('wtorek 1 grudnia: mogę'), const Offset(120, -40));
    await settle(tester);
    expect(api.sent('PUT /api/me/calendar'), isEmpty);
    expect(day('wtorek 1 grudnia: mogę'), findsOneWidget);
  });

  testWidgets('finishes a delayed write before sending the next choice for the same day', (tester) async {
    final api = server();
    final release = Completer<void>();
    var writes = 0;
    api.on('PUT /api/me/calendar', (_) async {
      if (++writes == 1) await release.future;
      return const Reply(204);
    });
    await open(tester, api);
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    expect(writes, 1);
    expect(find.text('Zapisuję…'), findsOneWidget);
    await tap(tester, tool('Chętnie'));
    await tap(tester, day('wtorek 1 grudnia: nie mogę'));
    expect(writes, 1); // the second waits for the first
    release.complete();
    await settle(tester);
    expect(find.text('Zapisane'), findsOneWidget);
    expect([for (final day in written(api)) day['state']], ['cannot', 'prefer']);
  });

  testWidgets('keeps a failed mark on screen and saves it again', (tester) async {
    final api = server();
    var fail = true;
    api.on('PUT /api/me/calendar', (_) => fail ? const Reply(503, {'detail': 'x'}) : const Reply(204));
    await open(tester, api);
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tester.pump(const Duration(seconds: 30)); // the app's own retries
    await settle(tester);
    expect(find.text('Nie zapisano'), findsOneWidget);
    expect(day('wtorek 1 grudnia: nie mogę'), findsOneWidget);
    fail = false;
    await tap(tester, find.text('Zapisz jeszcze raz'));
    expect(find.text('Zapisane'), findsOneWidget);
    expect(written(api).last, {'date': '2026-12-01', 'state': 'cannot', 'one_shift': false});
  });

  testWidgets('says why pulling down does not refresh while a mark is unsaved', (tester) async {
    final api = server();
    var fail = true;
    api.on('PUT /api/me/calendar', (_) => fail ? const Reply(503, {'detail': 'x'}) : const Reply(204));
    await open(tester, api);
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tester.pump(const Duration(seconds: 30)); // the app's own retries
    await settle(tester);
    final reads = api.sent('GET /api/me/calendar').length;
    final list = find.descendant(of: find.byType(RefreshIndicator), matching: find.byType(Scrollable)).first;
    await tester.drag(list, const Offset(0, 3000)); // back to the top
    await settle(tester);
    await tester.fling(list, const Offset(0, 400), 1000);
    await settle(tester);
    expect(find.text('Masz niezapisane zmiany. Zapisz je, zanim odświeżysz.'), findsOneWidget);
    expect(api.sent('GET /api/me/calendar').length, reads);
    expect(day('wtorek 1 grudnia: nie mogę'), findsOneWidget);
    fail = false;
    await tap(tester, find.widgetWithText(SnackBarAction, 'Zapisz jeszcze raz'));
    expect(find.text('Zapisane'), findsOneWidget);
  });

  testWidgets('asks before another month drops marks that did not save', (tester) async {
    final api = server();
    var fail = true;
    api.on('PUT /api/me/calendar', (_) => fail ? const Reply(503, {'detail': 'x'}) : const Reply(204));
    await open(tester, api);
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tester.pump(const Duration(seconds: 30)); // the app's own retries
    await settle(tester);
    expect(find.text('Nie zapisano'), findsOneWidget);

    await tap(tester, find.byTooltip('Następny miesiąc'));
    expect(find.text('Zmiany się nie zapisały'), findsOneWidget);
    fail = false;
    await tap(tester, inSheet(find.text('Zapisz jeszcze raz')));
    expect(find.text('Grudzień 2026'), findsOneWidget);
    expect(find.text('Zapisane'), findsOneWidget);
    expect(written(api).last, {'date': '2026-12-01', 'state': 'cannot', 'one_shift': false});

    fail = true;
    await tap(tester, day('środa 2 grudnia: mogę'));
    await tester.pump(const Duration(seconds: 30));
    await settle(tester);
    await tap(tester, find.byTooltip('Następny miesiąc'));
    await tap(tester, inSheet(find.text('Zmień miesiąc bez zapisu')));
    expect(find.text('Styczeń 2027'), findsOneWidget);
    expect(find.text('Zapisane'), findsOneWidget);
  });

  testWidgets('warns plainly that "chętnie" with hours blocks other shifts that day', (tester) async {
    await open(tester, server());
    await tap(tester, find.text('Godziny dnia'));
    expect(find.text('Stuknij dzień, żeby ustawić godziny.'), findsOneWidget);
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tap(tester, inSheet(find.text('Chętnie')));
    await tap(tester, find.text('Mogę tylko w tych godzinach'));
    expect(find.text('Zmiany spoza godzin 14:00–22:00 tego dnia nie dostaniesz.'), findsOneWidget);
  });

  testWidgets('keeps "nie mogę" for the whole day and points to "mogę" for part of a day', (tester) async {
    final api = server();
    await open(tester, api);
    await tap(tester, find.text('Godziny dnia'));
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tap(tester, find.text('Mogę tylko w tych godzinach'));
    await tap(tester, inSheet(find.text('Nie mogę')));
    expect(find.textContaining('w tych godzinach'), findsNothing);
    expect(find.textContaining('Możesz w części dnia? Wybierz „Mogę” i godziny'), findsOneWidget);
    await tap(tester, find.text('Zapisz ten dzień'));
    expect(written(api), [
      {'date': '2026-12-01', 'state': 'cannot', 'one_shift': false},
    ]);
  });

  testWidgets('saves two windows in a day with "albo" (only one shift)', (tester) async {
    final api = server();
    await open(tester, api);
    await tap(tester, find.text('Godziny dnia'));
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tap(tester, find.text('Mogę tylko w tych godzinach'));
    await pickTime(tester, 'Od', '6:00');
    await pickTime(tester, 'Do', '10:00');
    await tap(tester, find.text('Dodaj drugi przedział'));
    await pickTime(tester, 'Od', '16:00', which: 1);
    await tap(tester, find.text('Albo: tylko jedna zmiana'));
    expect(find.text('Zmiany spoza godzin 6:00–10:00 i 16:00–22:00 tego dnia nie dostaniesz.'), findsOneWidget);
    await tap(tester, find.text('Zapisz ten dzień'));
    expect(written(api), [
      {
        'date': '2026-12-01',
        'state': 'neutral',
        'from_time': '06:00',
        'to_time': '10:00',
        'from_time_2': '16:00',
        'to_time_2': '22:00',
        'one_shift': true,
      },
    ]);
    expect(day('wtorek 1 grudnia: mogę, tylko 06:00–10:00 albo 16:00–22:00 (jedna zmiana)'), findsOneWidget);
  });

  testWidgets('asks again about a long night, which is more likely swapped hours', (tester) async {
    await open(tester, server());
    await tap(tester, find.text('Godziny dnia'));
    await tap(tester, day('wtorek 1 grudnia: mogę'));
    await tap(tester, find.text('Mogę tylko w tych godzinach'));
    await pickTime(tester, 'Od', '20:00');
    await pickTime(tester, 'Do', '16:00');
    expect(find.textContaining('To 20 godzin: od 20:00 do 16:00 następnego dnia'), findsOneWidget);
    await tap(tester, find.text('Zamień: od 16:00 do 20:00'));
    expect(find.textContaining('To 20 godzin'), findsNothing);
    expect(find.text('Zapisz ten dzień'), findsOneWidget);
  });

  testWidgets('opens a day with its hours when it is tapped with the state it already has', (tester) async {
    await open(tester, server());
    await tap(tester, tool('Chętnie'));
    await tap(tester, day('piątek 4 grudnia: chętnie, tylko 22:00–06:00 (do rana)'));
    expect(inSheet(find.text('piątek 4 grudnia')), findsOneWidget);
    expect(inSheet(find.text('22:00')), findsOneWidget);
    expect(inSheet(find.text('6:00')), findsOneWidget);
  });

  testWidgets('shows saved hours between the half hours as they are', (tester) async {
    // Tests of PR #82 (26.11.2026): "nie mogę 9:15–11:45" saved windows the lists could not show, so they read 0:00.
    final rest = {
      'date': '2026-12-07',
      'state': 'neutral',
      'from_time': '00:00:00',
      'to_time': '09:15:00',
      'from_time_2': '11:45:00',
      'to_time_2': '00:00:00',
    };
    await open(tester, server(days: [rest]));
    await tap(tester, find.text('Zmień'));
    expect(inSheet(find.text('9:15')), findsOneWidget);
    expect(inSheet(find.text('11:45')), findsOneWidget);
  });

  testWidgets('opens hours saved without a start as starting at midnight', (tester) async {
    await open(
      tester,
      server(
        days: [
          {'date': '2026-12-07', 'state': 'neutral', 'to_time': '15:00:00'},
        ],
      ),
    );
    expect(find.text('mogę, tylko do 15:00'), findsOneWidget);
    await tap(tester, find.text('Zmień'));
    expect(inSheet(find.text('0:00')), findsOneWidget);
    expect(find.text('Zmiany spoza godzin 0:00–15:00 tego dnia nie dostaniesz.'), findsOneWidget);
  });

  testWidgets('cannot be changed when the company is read-only', (tester) async {
    await open(tester, server(readOnly: true));
    expect(rich('wstrzymany dostęp'), findsOneWidget);
    expect(day('wtorek 1 grudnia: mogę, nie da się zmienić'), findsOneWidget);
    expect(find.text('Wybierz, a potem zaznacz dni:'), findsNothing);
    expect(find.text('Wyślij kierownikowi'), findsNothing);
  });
}
