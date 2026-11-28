import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/features/requests/chat_parts.dart';
import 'package:grafikomat/router.dart';
import 'package:grafikomat/session/prefs.dart';
import 'package:material_ui/material_ui.dart';

import '../helpers.dart';

// The website's `RequestsSection.test.tsx` and `EmployeeChat.test.tsx`, case by case: "Twoje prośby" under the
// calendar of "Kiedy mogę", and the chat that opens from it or from the "Asystent" tab.

const december = <String, Object?>{
  'id': 'p1',
  'location_name': 'Wieliczka – Rynek',
  'start': '2026-12-01',
  'end': '2026-12-31',
  'status': 'collecting',
  'deadline': '2099-11-24',
  'editable': true,
  'assistant_reads': false,
};

final january = <String, Object?>{...december, 'start': '2027-01-01', 'end': '2027-01-31'};

final today = DateTime(2026, 11, 13, 9);

Map<String, Object?> request([Map<String, Object?> over = const {}]) => {
  'id': 'r1',
  'text': 'Wolałabym nie pracować w piątki.',
  'status': 'interpreted',
  'summary': 'Wolne w piątki, jeśli się da.',
  'reply': null,
  'cannot_marks': [],
  'notes': [],
  'created_at': '2026-11-01T10:00:00Z',
  ...over,
};

/// "Kiedy mogę" with its requests: [rows] answers every read of the list (called anew, so a test can change it).
FakeServer server({
  required List<Object?> Function() rows,
  Map<String, Object?>? asked = december,
  bool assistantReads = false,
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
    ..on(
      'GET /api/me/availability',
      (_) => Reply(200, {'period': asked, 'days': [], 'submitted_at': null, 'assistant_reads': assistantReads}),
    )
    ..on(
      'GET /api/me/calendar',
      (sent) => Reply(200, {
        'start': sent.query['start'],
        'end': sent.query['end'],
        'days': [],
        'locked': [],
        'unpublished': [],
        'period': asked,
        'submitted_at': null,
        'location_names': ['Rynek'],
      }),
    )
    ..on('GET /api/me/requests', (_) => Reply(200, rows()))
    ..on('PUT /api/me/calendar', (_) => const Reply(204));
}

/// "Kiedy mogę" on a phone-sized screen, scrolled to "Twoje prośby".
Future<ProviderContainer> open(WidgetTester tester, FakeServer server) async {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final container = await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'}, clock: () => today);
  container.read(routerProvider).go('/kiedy-moge');
  await settle(tester);
  await tester.ensureVisible(find.text('Twoje prośby'));
  await settle(tester);
  return container;
}

Future<void> tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pump();
  await tester.tap(finder);
  await settle(tester);
}

/// The button of "Twoje prośby" that opens the chat on its month.
Future<void> openChat(WidgetTester tester) =>
    tap(tester, find.textContaining(RegExp(r'^(Napisz do asystenta|Napisz prośbę|Pokaż rozmowę)$')));

/// What a part of the screen is called for screen readers ("Zapisane prośby").
Finder part(String label) => find.byWidgetPredicate((w) => w is Semantics && w.properties.label == label);

Finder within(Finder parent, Finder child) => find.descendant(of: parent, matching: child);

Finder rich(String text) => find.textContaining(text, findRichText: true);

Finder field(String label) => find.widgetWithText(TextField, label);

/// The tab at the bottom that opens the chat.
Finder chatTab(String label) => find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

/// Leaves the chat with the arrow at its top.
Future<void> back(WidgetTester tester) => tap(tester, find.byType(BackButton));

Object? body(FakeServer server, String route) => server.sent(route).single.body;

void main() {
  group('the chat', () {
    testWidgets('shows how the request was understood and lets the person say it is wrong', (tester) async {
      var rows = <Object?>[request()];
      final api = server(rows: () => rows)
        ..on('PATCH /api/me/requests/r1', (_) {
          rows = [
            request({'status': 'needs_manager', 'summary': null}),
          ];
          return Reply(200, rows.first);
        });
      await open(tester, api);
      expect(find.text('Asystent zrozumiał: Wolne w piątki, jeśli się da.'), findsOneWidget);

      await openChat(tester);
      expect(rich('Tak to zrozumieliśmy: Wolne w piątki, jeśli się da.'), findsOneWidget);
      await tap(tester, find.text('Nie o to mi chodziło'));
      // First a chance to write it again; handing it to the manager is the second choice.
      expect(tester.widget<TextField>(field('Napisz to inaczej')).controller!.text, 'Wolałabym nie pracować w piątki.');
      expect(api.sent('PATCH /api/me/requests/r1'), isEmpty);
      await tap(tester, find.text('Niech przeczyta kierownik'));
      expect(find.textContaining('Kierownik przeczyta tę prośbę sam'), findsOneWidget);
      expect(body(api, 'PATCH /api/me/requests/r1'), {'understood': false});
    });

    testWidgets('lets the person write a misunderstood request again', (tester) async {
      final api = server(rows: () => [request()], assistantReads: true)
        ..on('PATCH /api/me/requests/r1', (_) => Reply(200, request({'status': 'new', 'summary': null})));
      await open(tester, api);
      await openChat(tester);
      await tap(tester, find.text('Nie o to mi chodziło'));
      await tester.enterText(field('Napisz to inaczej'), 'Wolne tylko w piątki po południu.');
      await tap(tester, find.text('Wyślij poprawioną'));
      expect(body(api, 'PATCH /api/me/requests/r1'), {'text': 'Wolne tylko w piątki po południu.'});
    });

    testWidgets('shows a reading robot while the assistant reads a message, then the answer', (tester) async {
      var reading = true;
      final api = server(
        assistantReads: true,
        rows: () => [
          reading
              ? request({'status': 'new', 'summary': null, 'created_at': today.toUtc().toIso8601String()})
              : request({'created_at': today.toUtc().toIso8601String()}),
        ],
      );
      await open(tester, api);
      expect(find.text('Asystent myśli…'), findsOneWidget);
      await openChat(tester);
      expect(within(find.byType(ChatTyping), find.text('Myślę…')), findsOneWidget);
      expect(find.byType(ReadingRobot), findsOneWidget);
      expect(find.text('Wysłane'), findsOneWidget);

      // The list is asked again every 2 seconds while the assistant reads.
      reading = false;
      await tester.pump(const Duration(seconds: 2));
      await settle(tester);
      expect(find.text('Myślę…'), findsNothing);
      expect(rich('Tak to zrozumieliśmy'), findsOneWidget);
      expect(find.text('Zapisane w Twoich prośbach'), findsOneWidget);
    });

    testWidgets('offers to mark the days the person cannot work and shows calendar notes', (tester) async {
      final api = server(
        assistantReads: true,
        rows: () => [
          request({
            'reply': 'Powodzenia na sesji.',
            'summary': 'Wolne 14.12–16.12 („nie mogę”).',
            'cannot_marks': [
              {
                'days': ['2026-12-14', '2026-12-15'],
              },
            ],
            'notes': ['W kalendarzu masz „Chętnie” w dni, w które prośba mówi o wolnym: 15.12.'],
          }),
        ],
      );
      await open(tester, api);
      await openChat(tester);
      expect(find.text('Powodzenia na sesji.'), findsOneWidget);
      expect(find.textContaining('masz „Chętnie”'), findsOneWidget);
      expect(find.textContaining('nadal do pracy: 14.12, 15.12'), findsOneWidget);
      await tap(tester, find.text('Zaznacz „nie mogę”'));
      expect(body(api, 'PUT /api/me/calendar'), {
        'company_id': 'c1',
        'days': [
          {'date': '2026-12-14', 'state': 'cannot', 'one_shift': false},
          {'date': '2026-12-15', 'state': 'cannot', 'one_shift': false},
        ],
      });
      // The calendar of "Kiedy mogę" is read again, so it shows the marks once the chat is closed.
      final reads = api.sent('GET /api/me/calendar').length;
      await back(tester);
      expect(api.sent('GET /api/me/calendar').length, reads + 1);
    });

    testWidgets('marks the rest of the day as „Mogę” when the person cannot work some hours', (tester) async {
      // "We wtorki nie mogę od 9:00 do 11:00": "nie mogę" is always a whole day, so those days get "mogę do 9 i od 11".
      const rest = [
        {'start': '00:00', 'end': '09:00'},
        {'start': '11:00', 'end': '00:00'},
      ];
      final api = server(
        assistantReads: true,
        rows: () => [
          request({
            'summary': '1.12, 8.12 „Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00).',
            'cannot_marks': [
              {
                'days': ['2026-12-01'],
                'from_time': '09:00',
                'to_time': '11:00',
                'windows': rest,
                'prefer_days': [],
                'whole_day': true,
              },
              {
                'days': ['2026-12-08', '2026-12-15'],
                'from_time': '09:00',
                'to_time': '11:00',
                'windows': rest,
                'prefer_days': ['2026-12-15'],
                'whole_day': false,
              },
            ],
          }),
        ],
      );
      await open(tester, api);
      await openChat(tester);
      expect(
        find.textContaining('mają „Nie mogę” przez cały dzień, a prośba mówi tylko o godzinach 9:00–11:00: 1.12'),
        findsOneWidget,
      );
      expect(find.textContaining('nadal do pracy także w godzinach 9:00–11:00: 8.12, 15.12'), findsOneWidget);
      // Opening a whole day says what it costs, and that a whole day off can stay.
      expect(find.textContaining('Nie możesz przez cały dzień? Zostaw tak, jak jest'), findsOneWidget);
      // Until the button is pressed the generator knows nothing about those hours, so the text says so.
      expect(find.textContaining('Tego jeszcze nie ma w kalendarzu. Naciśnij przycisk'), findsOneWidget);
      final buttons = find.text('Zaznacz „Mogę” do 9:00 i od 11:00');
      expect(buttons, findsNWidgets(2));
      await tap(tester, buttons.first);
      expect(body(api, 'PUT /api/me/calendar'), {
        'company_id': 'c1',
        'days': [
          {
            'date': '2026-12-01',
            'state': 'neutral',
            'from_time': '00:00',
            'to_time': '09:00',
            'from_time_2': '11:00',
            'to_time_2': '00:00',
            'one_shift': false,
          },
        ],
      });
      await tap(tester, buttons.last);
      final days = (api.sent('PUT /api/me/calendar').last.body! as Map)['days'] as List;
      expect(
        [for (final day in days) ((day as Map)['date'], day['state'])],
        [
          ('2026-12-08', 'neutral'),
          ('2026-12-15', 'prefer'), // "chętnie" stays
        ],
      );
    });

    testWidgets("cuts the person's own hours and says which hours the calendar cannot keep", (tester) async {
      // Tests of PR #82 (26.11.2026): own hours 8–18 and "nie mogę od 9 do 11" gave no offer; 9–11 and 14–16 the
      // same day gave only the first.
      final api = server(
        assistantReads: true,
        rows: () => [
          request({
            'summary': '7.12 „Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00).',
            'parts': [
              {'summary': '7.12 „Mogę” tylko do 9:00 i od 11:00.', 'calendar_only': true, 'can_last': false},
            ],
            'cannot_marks': [
              {
                'days': ['2026-12-07'],
                'from_time': '09:00',
                'to_time': '11:00',
                'hours': [
                  {'start': '09:00', 'end': '11:00'},
                ],
                'windows': [
                  {'start': '08:00', 'end': '09:00'},
                  {'start': '11:00', 'end': '18:00'},
                ],
                'own': [
                  {'start': '08:00', 'end': '18:00'},
                ],
              },
              {
                'days': ['2026-12-08'],
                'from_time': '09:00',
                'to_time': '11:00',
                'hours': [
                  {'start': '09:00', 'end': '11:00'},
                  {'start': '14:00', 'end': '16:00'},
                ],
                'windows': [
                  {'start': '00:00', 'end': '09:00'},
                  {'start': '16:00', 'end': '00:00'},
                ],
                'dropped': [
                  {'start': '11:00', 'end': '14:00'},
                ],
              },
            ],
          }),
        ],
      );
      await open(tester, api);
      await openChat(tester);
      expect(
        find.text('W kalendarzu masz w te dni godziny 8:00–18:00, a prośba mówi, że nie możesz 9:00–11:00: 7.12.'),
        findsOneWidget,
      );
      expect(find.textContaining('godzinach 9:00–11:00 i 14:00–16:00: 8.12'), findsOneWidget);
      expect(
        find.textContaining('Kalendarz mieści dwa przedziały godzin dziennie, więc 11:00–14:00 też będzie bez pracy'),
        findsOneWidget,
      );
      // Nothing reaches the generator until the button: the card says so instead of "Generator spróbuje".
      expect(
        find.textContaining('Generator nie dostaje tej prośby. Godziny, w których nie możesz, zaczną obowiązywać'),
        findsOneWidget,
      );
      expect(find.text('Na stałe'), findsNothing);
      await tap(tester, find.text('Zaznacz „Mogę” 8:00–9:00 i 11:00–18:00'));
      expect(body(api, 'PUT /api/me/calendar'), {
        'company_id': 'c1',
        'days': [
          {
            'date': '2026-12-07',
            'state': 'neutral',
            'from_time': '08:00',
            'to_time': '09:00',
            'from_time_2': '11:00',
            'to_time_2': '18:00',
            'one_shift': false,
          },
        ],
      });
    });

    testWidgets('in a mixed request says what the generator gets and what counts only here', (tester) async {
      // Piotr, 26.11.2026: "w piątki wolę salę, a we wtorki nie mogę od 9 do 11" may last only in its position wish.
      final api = server(
        assistantReads: true,
        rows: () => [
          request({
            'summary':
                'Chętniej stanowisko „Sala” w piątki (inne też mogą być); we wtorki „Mogę” tylko do 9:00 i od 11:00.',
            'can_last': true,
            'parts': [
              {
                'summary': 'Chętniej stanowisko „Sala” w piątki (inne też mogą być).',
                'calendar_only': false,
                'can_last': true,
              },
              {'summary': 'We wtorki „Mogę” tylko do 9:00 i od 11:00.', 'calendar_only': true, 'can_last': false},
            ],
          }),
        ],
      );
      await open(tester, api);
      await openChat(tester);
      expect(
        find.text(
          'Generator grafiku spróbuje spełnić: chętniej stanowisko „Sala” w piątki (inne też mogą być). Godziny, w '
          'których nie możesz, obowiązują tak, jak są zaznaczone w kalendarzu.',
        ),
        findsOneWidget,
      );
      expect(find.text('Na stałe'), findsOneWidget);
      expect(find.text('Tylko w grudniu: we wtorki „Mogę” tylko do 9:00 i od 11:00.'), findsOneWidget);
    });

    testWidgets('a request nobody interpreted simply goes to the manager', (tester) async {
      final api = server(
        asked: {...december, 'editable': false},
        rows: () => [
          request({'status': 'needs_manager', 'summary': null}),
        ],
      );
      await open(tester, api);
      await openChat(tester);
      expect(find.textContaining('Kierownik przeczyta tę prośbę sam'), findsOneWidget);
      expect(rich('Tak to zrozumieliśmy'), findsNothing);
      expect(
        find.text('Prośby na ten okres są już zamknięte. Jeśli coś się zmieniło, porozmawiaj z kierownikiem.'),
        findsOneWidget,
      );
      expect(find.byType(ChatComposer), findsNothing);
    });

    testWidgets('says that the assistant also reads the request, only when it does', (tester) async {
      await open(tester, server(rows: () => [], assistantReads: true));
      await openChat(tester);
      expect(find.text('W czym pomóc?'), findsOneWidget);
      await tap(tester, find.byTooltip('O prośbach i Twoich danych'));
      expect(find.textContaining('sprawdza to, co widzisz w aplikacji'), findsOneWidget);
      expect(find.textContaining('nazwy zmian i nazwy Twoich lokali'), findsOneWidget);
      expect(find.textContaining('Reszty rozmowy nie widzą'), findsOneWidget);
      expect(find.textContaining('Przeczyta to tylko kierownik'), findsNothing);
    });

    testWidgets('keeps who reads the messages one tap away under the field, in short paragraphs', (tester) async {
      await open(tester, server(rows: () => [], assistantReads: true));
      await openChat(tester);
      await tap(tester, find.widgetWithText(TextButton, 'O prośbach i Twoich danych'));
      final text = tester.widget<Text>(find.textContaining('Reszty rozmowy nie widzą')).data!;
      expect(text.split('\n\n'), hasLength(4));
      expect(text.split('\n\n').last, startsWith('Kierownik i jego asystent AI widzą'));
    });

    testWidgets('says that only the manager reads the request when the assistant is off', (tester) async {
      await open(tester, server(rows: () => []));
      expect(find.text('Napisz prośbę'), findsOneWidget);
      await openChat(tester);
      expect(find.text('Prośby do kierownika'), findsOneWidget);
      expect(find.text('Co warto uwzględnić w Twoim grafiku?'), findsOneWidget);
      expect(find.text('Wiadomość dla kierownika.'), findsOneWidget);
      await tap(tester, find.byTooltip('O prośbach i Twoich danych'));
      expect(find.textContaining('Przeczyta to tylko kierownik'), findsOneWidget);
      expect(find.textContaining('sprawdza to, co widzisz'), findsNothing);
    });

    testWidgets('keeps superseded requests visible without an edit action', (tester) async {
      await open(
        tester,
        server(
          rows: () => [
            request({'status': 'superseded', 'summary': null}),
          ],
        ),
      );
      await openChat(tester);
      expect(find.textContaining('Ta prośba została zastąpiona'), findsOneWidget);
      expect(find.text('Historia prośby'), findsOneWidget);
      expect(find.byTooltip('Edytuj prośbę'), findsNothing);
      expect(find.text('Nie o to mi chodziło'), findsNothing);
    });

    testWidgets('shows an answer without claiming it was sent to the manager', (tester) async {
      await open(
        tester,
        server(
          rows: () => [
            request({'status': 'answered', 'summary': null, 'reply': 'W listopadzie masz 120 godzin.'}),
            request({
              'id': 'old',
              'status': 'answered',
              'summary': 'Starsza odpowiedź zapisana jako opis.',
              'created_at': '2026-11-02T10:00:00Z',
            }),
          ],
        ),
      );
      await openChat(tester);
      expect(find.text('W listopadzie masz 120 godzin.'), findsOneWidget);
      expect(find.text('Starsza odpowiedź zapisana jako opis.'), findsOneWidget);
      expect(find.text('Niech przeczyta kierownik'), findsNWidgets(2));
      expect(find.text('Odpowiedź asystenta'), findsNWidgets(2));
      expect(find.text('Zapisane w Twoich prośbach'), findsNothing);
    });

    testWidgets("shows the assistant's question and asks for an answer in the field", (tester) async {
      await open(
        tester,
        server(
          assistantReads: true,
          rows: () => [
            request({
              'text': 'Chcę mniej pracować.',
              'status': 'answered',
              'summary': null,
              'question': 'Ile najwyżej godzin w tygodniu chcesz pracować?',
              'waiting': true,
              'can_answer': true,
            }),
          ],
        ),
      );
      // "Twoje prośby" says it is not saved yet, so it is not lost quietly.
      final waiting = part('Czekają na Twoją odpowiedź');
      expect(
        within(waiting, find.text('Nie jest zapisana. Asystent pyta: Ile najwyżej godzin w tygodniu chcesz pracować?')),
        findsOneWidget,
      );
      expect(part('Zapisane prośby'), findsNothing);
      await tap(tester, within(waiting, find.text('Odpowiedz')));
      expect(find.text('Ile najwyżej godzin w tygodniu chcesz pracować?'), findsOneWidget);
      expect(find.text('Asystent dopytuje'), findsOneWidget);
      expect(find.text('Odpowiedz niżej. Do tego czasu niczego nie zapisuję.'), findsOneWidget);
      final composer = tester.widget<TextField>(find.byType(TextField));
      expect(composer.decoration!.labelText, 'Twoja wiadomość');
      expect(composer.decoration!.hintText, 'Odpowiedz asystentowi…');
    });

    testWidgets('lets the employee forward a misclassified question to the manager', (tester) async {
      var row = request({'status': 'answered', 'summary': 'Odpowiedź asystenta.'});
      final api = server(rows: () => [row])
        ..on('PATCH /api/me/requests/r1', (_) {
          row = request({'status': 'needs_manager', 'summary': null});
          return Reply(200, row);
        });
      await open(tester, api);
      await openChat(tester);
      await tap(tester, find.text('Niech przeczyta kierownik'));
      expect(find.textContaining('Kierownik przeczyta tę prośbę sam'), findsOneWidget);
      expect(body(api, 'PATCH /api/me/requests/r1'), {'understood': false});
    });

    testWidgets('does not send on Enter, only with the button, and keeps an unsent message', (tester) async {
      var rows = <Object?>[];
      final api = server(rows: () => rows, assistantReads: true)
        ..on('POST /api/me/requests', (sent) {
          rows = [
            request({'text': (sent.body! as Map)['text'], 'status': 'new', 'summary': null}),
          ];
          return Reply(201, rows.first);
        });
      await open(tester, api);
      await openChat(tester);
      await tester.enterText(field('Twoja wiadomość'), 'Wolę piątki rano');
      await tester.testTextInput.receiveAction(TextInputAction.newline);
      await settle(tester);
      expect(api.sent('POST /api/me/requests'), isEmpty);

      // Leaving the chat keeps what was written.
      await back(tester);
      await openChat(tester);
      expect(tester.widget<TextField>(field('Twoja wiadomość')).controller!.text, startsWith('Wolę piątki rano'));

      await tester.enterText(field('Twoja wiadomość'), 'Wolę piątki rano');
      await tap(tester, find.text('Wyślij'));
      expect(body(api, 'POST /api/me/requests'), {'company_id': 'c1', 'period_id': 'p1', 'text': 'Wolę piątki rano'});
      expect(find.text('Wolę piątki rano'), findsOneWidget);
      expect(tester.widget<TextField>(field('Twoja wiadomość')).controller!.text, '');
    });

    testWidgets('lets the employee forward a rejected request to the manager without claiming it was sent', (
      tester,
    ) async {
      final api = server(
        assistantReads: true,
        rows: () => [
          request({'status': 'rejected', 'summary': 'Pomagam tylko ustalać preferencje.'}),
        ],
      )..on('PATCH /api/me/requests/r1', (_) => Reply(200, request({'status': 'needs_manager', 'summary': null})));
      await open(tester, api);
      await openChat(tester);
      expect(find.text('Pomagam tylko ustalać preferencje.'), findsOneWidget);
      expect(find.text('Odrzucona'), findsOneWidget);
      expect(find.text('Zapisane w Twoich prośbach'), findsNothing);
      await tap(tester, find.text('Przekaż kierownikowi'));
      expect(body(api, 'PATCH /api/me/requests/r1'), {'understood': false});
    });

    testWidgets('removes a message that is not a request after a confirmation', (tester) async {
      var rows = <Object?>[
        request({'status': 'answered', 'summary': null, 'reply': 'Masz 120 godzin.'}),
      ];
      final api = server(rows: () => rows, assistantReads: true)
        ..on('DELETE /api/me/requests/r1', (_) {
          rows = [];
          return const Reply(204);
        });
      await open(tester, api);
      await openChat(tester);
      await tap(tester, find.byTooltip('Usuń prośbę'));
      expect(api.sent('DELETE /api/me/requests/r1'), isEmpty);
      await tap(tester, find.text('Tak, usuń'));
      expect(api.sent('DELETE /api/me/requests/r1'), hasLength(1));
      expect(find.text('W czym pomóc?'), findsOneWidget);
    });
  });

  group('"Twoje prośby"', () {
    testWidgets('lists only understood and forwarded requests, outside the chat', (tester) async {
      await open(
        tester,
        server(
          assistantReads: true,
          rows: () => [
            request(),
            request({'id': 'r2', 'text': 'Ile mam godzin?', 'status': 'answered', 'summary': 'Masz 120 godzin.'}),
            request({'id': 'r3', 'text': 'Kup mi kawę', 'status': 'rejected', 'summary': 'Pomagam tylko z grafikiem.'}),
            request({'id': 'r4', 'text': 'Potrzebuję wolnej soboty.', 'status': 'needs_manager', 'summary': null}),
          ],
        ),
      );
      final saved = part('Zapisane prośby');
      expect(within(saved, find.text('Asystent zrozumiał: Wolne w piątki, jeśli się da.')), findsOneWidget);
      expect(within(saved, find.text('Potrzebuję wolnej soboty.')), findsOneWidget);
      expect(within(saved, find.text('Kierownik przeczyta ją sam.')), findsOneWidget);
      expect(find.textContaining('Masz 120 godzin.'), findsNothing);
      expect(find.text('Kup mi kawę'), findsNothing);
      expect(find.textContaining('nie jest prośbą'), findsNothing);
    });

    testWidgets('leaves a trace in the window when the newest message was rejected', (tester) async {
      await open(
        tester,
        server(
          assistantReads: true,
          rows: () => [
            request(),
            request({
              'id': 'r3',
              'text': 'Kup mi kawę',
              'status': 'rejected',
              'summary': 'Pomagam tylko z grafikiem.',
              'created_at': '2026-11-02T10:00:00Z',
            }),
          ],
        ),
      );
      expect(find.textContaining('została odrzucona i nie jest prośbą'), findsOneWidget);
      await tap(tester, find.text('Pokaż odpowiedź'));
      expect(find.text('Pomagam tylko z grafikiem.'), findsOneWidget);
    });

    testWidgets('shows the earlier messages of a request the assistant asks about again', (tester) async {
      await open(
        tester,
        server(
          assistantReads: true,
          rows: () => [
            request({
              'id': 'q2',
              'text': 'Trochę mniej.',
              'status': 'answered',
              'summary': null,
              'question': 'Ile najwyżej w tygodniu?',
              'waiting': true,
              'can_answer': true,
              'exchange': [
                {'text': 'Chcę mniej pracować.', 'question': 'Ile godzin?'},
              ],
            }),
          ],
        ),
      );
      final waiting = part('Czekają na Twoją odpowiedź');
      final texts = [for (final text in tester.widgetList<Text>(within(waiting, find.byType(Text)))) text.data];
      expect(texts.take(3), [
        'Chcę mniej pracować.',
        'Trochę mniej.',
        'Nie jest zapisana. Asystent pyta: Ile najwyżej w tygodniu?',
      ]);
    });

    testWidgets('lets a question the assistant no longer remembers be written again', (tester) async {
      final api = server(
        assistantReads: true,
        rows: () => [
          request({
            'id': 'q',
            'text': 'Chcę mniej pracować.',
            'status': 'answered',
            'summary': null,
            'question': 'Ile godzin?',
            'waiting': true,
          }),
          request({'id': 'later', 'created_at': '2026-11-02T10:00:00Z'}),
        ],
      )..on('PATCH /api/me/requests/q', (_) => Reply(200, request({'status': 'new', 'summary': null})));
      await open(tester, api);
      final waiting = part('Czekają na Twoją odpowiedź');
      // Older than the assistant remembers: the chat would not take the next message as its answer.
      expect(within(waiting, find.text('Odpowiedz')), findsNothing);
      await tap(tester, within(waiting, find.text('Napisz ją od nowa')));
      expect(find.textContaining('Napisz całą prośbę razem z odpowiedzią na pytanie.'), findsOneWidget);
      await tester.enterText(field('Treść prośby'), 'Najwyżej 30 godzin w tygodniu.');
      await tap(tester, find.text('Zapisz prośbę'));
      expect(body(api, 'PATCH /api/me/requests/q'), {'text': 'Najwyżej 30 godzin w tygodniu.'});
    });

    testWidgets('edits a saved request in the window', (tester) async {
      final api = server(rows: () => [request()], assistantReads: true)
        ..on('PATCH /api/me/requests/r1', (_) => Reply(200, request()));
      await open(tester, api);
      await tap(tester, find.byTooltip('Edytuj prośbę'));
      expect(
        find.textContaining('Po zmianie tekstu zewnętrzny asystent AI przeczyta prośbę ponownie.'),
        findsOneWidget,
      );
      await tester.enterText(field('Treść prośby'), 'Wolę piątki rano.');
      await tap(tester, find.text('Zapisz prośbę'));
      expect(body(api, 'PATCH /api/me/requests/r1'), {'text': 'Wolę piątki rano.'});
      expect(field('Treść prośby'), findsNothing);
    });

    testWidgets('removes a saved request after a confirmation', (tester) async {
      final api = server(rows: () => [request()])..on('DELETE /api/me/requests/r1', (_) => const Reply(204));
      await open(tester, api);
      await tap(tester, find.byTooltip('Usuń prośbę'));
      expect(find.text('Usunąć tę prośbę?'), findsOneWidget);
      expect(api.sent('DELETE /api/me/requests/r1'), isEmpty);
      await tap(tester, find.text('Tak, usuń'));
      expect(api.sent('DELETE /api/me/requests/r1'), hasLength(1));
    });

    testWidgets('offers no edits once the period is closed', (tester) async {
      await open(tester, server(asked: {...december, 'editable': false}, rows: () => [request()]));
      expect(find.text('Asystent zrozumiał: Wolne w piątki, jeśli się da.'), findsOneWidget);
      expect(find.byTooltip('Edytuj prośbę'), findsNothing);
      expect(find.byTooltip('Usuń prośbę'), findsNothing);
      expect(find.text('Pokaż rozmowę'), findsOneWidget);
      await tap(tester, find.text('Pokaż rozmowę'));
      expect(find.textContaining('Prośby na ten okres są już zamknięte.'), findsOneWidget);
    });

    testWidgets('says why nothing can be written while the company has no access', (tester) async {
      await open(tester, server(rows: () => [request()], readOnly: true));
      await tap(tester, find.text('Pokaż rozmowę'));
      expect(find.text('Wolałabym nie pracować w piątki.'), findsOneWidget);
      expect(find.textContaining('Firma ma teraz wstrzymany dostęp do aplikacji, więc nie napiszesz'), findsOneWidget);
      expect(find.textContaining('Prośby na ten okres są już zamknięte.'), findsNothing);
    });

    testWidgets('says plainly when there are no requests yet', (tester) async {
      await open(tester, server(rows: () => []));
      expect(find.textContaining('Nie masz jeszcze próśb. Napisz, czego kalendarz nie powie'), findsOneWidget);
    });

    testWidgets('says when the requests could not be read and reads them again', (tester) async {
      var fail = true;
      final api = server(rows: () => [request()])
        ..on('GET /api/me/requests', (_) => fail ? const Reply(500) : Reply(200, [request()]));
      await open(tester, api);
      expect(find.text('Nie udało się wczytać Twoich próśb.'), findsOneWidget);
      fail = false;
      await tap(tester, find.text('Spróbuj ponownie'));
      expect(find.text('Asystent zrozumiał: Wolne w piątki, jeśli się da.'), findsOneWidget);
    });
  });

  group('reports of other hours in the chat', () {
    Map<String, Object?> proposal([Map<String, Object?> over = const {}]) => {
      'assignment_id': 'as1',
      'date': '2026-11-20',
      'start_time': '06:00',
      'end_time': '11:00',
      'planned_start_time': '06:00',
      'planned_end_time': '14:00',
      'difference_minutes': -180,
      'location_name': 'Rynek',
      'position_name': 'Sprzedawca',
      'reason': 'źle się czuję',
      'sent_status': null,
      ...over,
    };

    testWidgets('sends a prepared report only when the person presses the button', (tester) async {
      var sent = false;
      final api =
          server(
            asked: null,
            assistantReads: true,
            rows: () => [
              request({
                'text': 'Źle się czuję, wyjdę o 11.',
                'status': 'answered',
                'summary': null,
                'reply': 'Przygotowałem zgłoszenie innych godzin.',
                'hours_reports': [
                  proposal(sent ? {'sent_status': 'pending'} : {}),
                ],
              }),
            ],
          )..on('POST /api/me/hours-changes', (_) {
            sent = true;
            return const Reply(201, {
              'id': 'h1',
              'status': 'pending',
              'employee_id': 'e1',
              'employee_name': 'Ola Nowak',
              'location_id': 'l1',
              'location_name': 'Rynek',
              'date': '2026-11-20',
              'position_name': 'Sprzedawca',
              'planned_start_time': '06:00',
              'planned_end_time': '14:00',
              'planned_hours': 8,
              'start_time': '06:00',
              'end_time': '11:00',
              'hours': 5,
              'difference_minutes': -180,
              'reason': 'źle się czuję',
              'by_manager': false,
              'created_at': '2026-11-13T10:15:00Z',
              'decided_at': null,
              'decided_by_name': '',
              'assignment_id': 'as1',
            });
          });
      await open(tester, api);
      await openChat(tester);
      expect(api.sent('GET /api/me/requests').last.query, {'company_id': 'c1', 'month': '2026-11-01'});
      final card = part('Zgłoszenia innych godzin');
      expect(within(card, rich('piątek 20 listopada: 6:00–11:00 zamiast 6:00–14:00 (krócej o 3 h)')), findsOneWidget);
      expect(within(card, find.textContaining('Powód: źle się czuję')), findsOneWidget);
      expect(api.sent('POST /api/me/hours-changes'), isEmpty); // nothing goes by itself

      await tap(tester, within(card, find.text('Wyślij kierownikowi')));
      expect(within(card, find.text('Wysłane. Czeka na kierownika.')), findsOneWidget);
      expect(body(api, 'POST /api/me/hours-changes'), {
        'assignment_id': 'as1',
        'start_time': '06:00',
        'end_time': '11:00',
        'reason': 'źle się czuję',
        'request_id': 'r1',
      });
    });

    testWidgets('says when the shift is gone or the manager decided', (tester) async {
      await open(
        tester,
        server(
          asked: null,
          assistantReads: true,
          rows: () => [
            request({
              'status': 'answered',
              'summary': null,
              'reply': 'Gotowe.',
              'hours_reports': [
                proposal({'assignment_id': null}),
                proposal({'date': '2026-11-19', 'sent_status': 'approved'}),
              ],
            }),
          ],
        ),
      );
      await openChat(tester);
      expect(find.textContaining('nie masz już tej zmiany, więc tego zgłoszenia nie wyślesz'), findsOneWidget);
      expect(find.text('Kierownik zatwierdził te godziny.'), findsOneWidget);
      expect(find.text('Wyślij kierownikowi'), findsNothing);
    });
  });

  group('requests that last', () {
    testWidgets('switches a saved request between this month only and lasting', (tester) async {
      final api = server(
        asked: january,
        rows: () => [
          request({'can_last': true, 'lasting': false}),
        ],
      )..on('PATCH /api/me/requests/r1', (sent) => Reply(200, request({'can_last': true, ...sent.body! as Map})));
      await open(tester, api);
      final only = find
          .ancestor(
            of: find.text('Tylko w styczniu'),
            matching: find.byWidgetPredicate((w) => w is Semantics && w.properties.selected != null),
          )
          .first;
      expect(tester.widget<Semantics>(only).properties.selected, isTrue);
      await tap(tester, find.text('Na stałe'));
      expect(body(api, 'PATCH /api/me/requests/r1'), {'lasting': true});
    });

    testWidgets('offers no choice for a request about concrete days', (tester) async {
      await open(
        tester,
        server(
          asked: january,
          rows: () => [
            request({'can_last': false}),
          ],
        ),
      );
      expect(find.text('Asystent zrozumiał: Wolne w piątki, jeśli się da.'), findsOneWidget);
      expect(find.text('Na stałe'), findsNothing);
    });

    testWidgets('lists a lasting request from an earlier month and ends it from this one', (tester) async {
      const carried = {'lasting': true, 'carried_from': '2026-12-01'};
      var rows = <Object?>[request(carried)];
      final api = server(asked: january, rows: () => rows)
        ..on('POST /api/me/requests/r1/end', (_) {
          rows = [
            request({...carried, 'ended': true, 'ended_by': 'employee', 'ends_from': '2027-01-01'}),
          ];
          return Reply(200, rows.first);
        });
      await open(tester, api);
      expect(find.textContaining(RegExp(r'^Na stałe od grudnia\. Asystent zrozumiał')), findsOneWidget);
      // It belongs to December: here it can only be ended, not edited or removed.
      expect(find.byTooltip('Edytuj prośbę'), findsNothing);
      await tap(tester, find.text('Zakończ'));
      expect(find.text('Zakończyć od stycznia?'), findsOneWidget);
      await tap(tester, find.text('Tak, zakończ'));
      expect(find.text('Zakończona: nie obowiązuje od stycznia.'), findsOneWidget);
      expect(body(api, 'POST /api/me/requests/r1/end'), {'company_id': 'c1', 'period_id': 'p1', 'ended': true});
      expect(find.text('Przywróć'), findsOneWidget);
    });

    testWidgets("offers this month's days of a lasting „nie mogę” written earlier", (tester) async {
      // 27.11.2026: "na stałe we wtorki nie mogę od 9 do 11" may last; each month offers its own Tuesdays.
      const rest = [
        {'start': '00:00', 'end': '09:00'},
        {'start': '11:00', 'end': '00:00'},
      ];
      final api = server(
        asked: january,
        rows: () => [
          request({
            'text': 'Na stałe we wtorki nie mogę od 9 do 11.',
            'summary': 'We wtorki „Mogę” tylko do 9:00 i od 11:00.',
            'lasting': true,
            'carried_from': '2026-12-01',
            'cannot_marks': [
              {
                'days': ['2027-01-05', '2027-01-12'],
                'from_time': '09:00',
                'to_time': '11:00',
                'windows': rest,
                'prefer_days': [],
                'whole_day': false,
              },
            ],
          }),
        ],
      );
      await open(tester, api);
      final calendarReads = api.sent('GET /api/me/calendar').length;
      await tap(tester, find.text('Zaznacz „Mogę” do 9:00 i od 11:00'));
      expect(body(api, 'PUT /api/me/calendar'), {
        'company_id': 'c1',
        'days': [
          for (final date in ['2027-01-05', '2027-01-12'])
            {
              'date': date,
              'state': 'neutral',
              'from_time': '00:00',
              'to_time': '09:00',
              'from_time_2': '11:00',
              'to_time_2': '00:00',
              'one_shift': false,
            },
        ],
      });
      // "Kiedy mogę" above reads its calendar again, so the days show the new hours.
      expect(api.sent('GET /api/me/calendar').length, greaterThan(calendarReads));
    });

    testWidgets('offers no days of a lasting „nie mogę” once it is ended', (tester) async {
      await open(
        tester,
        server(
          asked: january,
          rows: () => [
            request({
              'lasting': true,
              'carried_from': '2026-12-01',
              'ended': true,
              'ended_by': 'employee',
              'ends_from': '2027-01-01',
              'cannot_marks': [
                {
                  'days': ['2027-01-05'],
                  'from_time': null,
                  'to_time': null,
                  'windows': [],
                  'prefer_days': [],
                  'whole_day': false,
                },
              ],
            }),
          ],
        ),
      );
      expect(find.text('Zaznacz „nie mogę”'), findsNothing);
    });

    testWidgets('does not bring back a request the manager ended', (tester) async {
      await open(
        tester,
        server(
          asked: january,
          rows: () => [
            request({
              'lasting': true,
              'carried_from': '2026-12-01',
              'ended': true,
              'ended_by': 'manager',
              'ends_from': '2027-01-01',
            }),
          ],
        ),
      );
      expect(find.textContaining('Zakończył ją kierownik.'), findsOneWidget);
      expect(find.text('Przywróć'), findsNothing);
    });

    testWidgets("keeps lasting requests from earlier months out of this month's chat", (tester) async {
      await open(
        tester,
        server(
          asked: january,
          assistantReads: true,
          rows: () => [
            request({'id': 'old', 'text': 'Nie z Zuzanną.', 'lasting': true, 'carried_from': '2026-12-01'}),
            request({'id': 'new', 'text': 'Wolę ranne zmiany.'}),
          ],
        ),
      );
      await openChat(tester);
      final chat = part('Twoje prośby o grafiku');
      expect(within(chat, find.text('Wolę ranne zmiany.')), findsOneWidget);
      expect(within(chat, find.text('Nie z Zuzanną.')), findsNothing);
    });
  });

  group('the "Asystent" tab', () {
    List<Map<String, String>> asked(FakeServer api) => [
      for (final sent in api.sent('GET /api/me/requests')) sent.query,
    ];

    Future<void> openApp(WidgetTester tester, FakeServer api) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await pumpApp(tester, api, stored: {Prefs.sessionKey: 'k'}, clock: () => today);
    }

    testWidgets('opens the conversation of the period the manager asked for', (tester) async {
      final api = server(rows: () => [], assistantReads: true)
        ..on('GET /api/me/schedule', (_) => Reply(200, scheduleJson()));
      await openApp(tester, api);
      await tap(tester, chatTab('Asystent'));
      expect(field('Twoja wiadomość'), findsOneWidget);
      expect(asked(api), [
        {'company_id': 'c1', 'period_id': 'p1'},
      ]);
      // Written on another screen, a request still says which month it is for.
      expect(find.text('Prośby na grudzień 2026.'), findsOneWidget);
      expect(find.text('Asystent'), findsWidgets);
    });

    testWidgets('talks about this month before the manager asks', (tester) async {
      final api = server(rows: () => [], asked: null, assistantReads: true);
      await openApp(tester, api);
      await tap(tester, chatTab('Asystent'));
      expect(asked(api), [
        {'company_id': 'c1', 'month': '2026-11-01'},
      ]);
      expect(find.text('Prośby na listopad 2026.'), findsOneWidget);
    });

    testWidgets('on "Kiedy mogę" talks about the month on screen', (tester) async {
      final api = server(rows: () => [], assistantReads: true);
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      final container = await pumpApp(tester, api, stored: {Prefs.sessionKey: 'k'}, clock: () => today);
      container.read(routerProvider).go('/kiedy-moge');
      await settle(tester);
      // December (the asked period) first, then January: no period there yet, so the month itself.
      await tap(tester, find.byTooltip('Następny miesiąc'));
      expect(find.text('Styczeń 2027'), findsOneWidget);
      await tap(tester, chatTab('Asystent'));
      expect(find.text('W czym pomóc?'), findsOneWidget);
      expect(find.text('Prośby na styczeń 2027.'), findsOneWidget);
      expect(asked(api).last, {'company_id': 'c1', 'month': '2027-01-01'});

      // Elsewhere the chat goes back to the period the manager asked for.
      await back(tester);
      await tap(tester, chatTab('Mój grafik'));
      await tap(tester, chatTab('Asystent'));
      expect(find.text('Prośby na grudzień 2026.'), findsOneWidget);
    });

    testWidgets('is called "Prośby" when the assistant is off', (tester) async {
      await openApp(tester, server(rows: () => []));
      expect(chatTab('Prośby'), findsOneWidget);
      expect(chatTab('Asystent'), findsNothing);
    });

    testWidgets('has no tab while the company has no access', (tester) async {
      await openApp(tester, server(rows: () => [], readOnly: true));
      expect(chatTab('Mój grafik'), findsOneWidget);
      expect(chatTab('Asystent'), findsNothing);
      expect(chatTab('Prośby'), findsNothing);
    });

    testWidgets('lets the tab labels grow with the text size only as far as they fit', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 1.3;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      double labelSize() => MediaQuery.textScalerOf(tester.element(chatTab('Asystent'))).scale(12);

      // A phone: "Powiadomienia" (in the tests' wide font) would not fit even at the normal size, so no growth.
      await openApp(tester, server(rows: () => [], assistantReads: true));
      expect(labelSize(), 12);

      // A wide screen: the labels grow, but not past the size at which "Powiadomienia" still fits its tab.
      tester.view.physicalSize = const Size(2400, 2532);
      await settle(tester);
      expect(labelSize(), greaterThan(12));
      expect(labelSize(), lessThan(12 * 1.3));
      final label = tester.renderObject<RenderParagraph>(chatTab('Powiadomienia'));
      expect(label.getMaxIntrinsicWidth(double.infinity), lessThanOrEqualTo(label.size.width + 0.5));
    });
  });
}
