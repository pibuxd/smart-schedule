import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/api/client.dart';
import 'package:grafikomat/session/prefs.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

void main() {
  testWidgets('logs in with the phone number and the SMS code, then opens "Mój grafik"', (tester) async {
    var loggedIn = false;
    final server = FakeServer()
      ..on('GET /api/me', (_) => loggedIn ? Reply(200, meJson()) : const Reply(401, {'detail': 'Zaloguj się.'}))
      ..on(
        'POST /api/auth/request-code',
        (_) => const Reply(200, {'phone': '+48511200002', 'expires_in_s': 600, 'resend_after_s': 60}),
      )
      ..on('POST /api/auth/verify-code', (_) {
        loggedIn = true;
        return Reply(200, meJson(), {'X-Grafikomat-Session': 'fresh'});
      });
    final container = await pumpApp(tester, server);

    expect(find.text('Zaloguj się'), findsOneWidget);
    await tester.tap(find.text('Wyślij kod SMS'));
    await settle(tester);
    expect(find.text('Wpisz 9 cyfr numeru, na przykład 512 345 678.'), findsOneWidget);
    expect(server.sent('POST /api/auth/request-code'), isEmpty);

    await tester.enterText(find.byType(TextField), '511 200 002');
    await tester.tap(find.text('Wyślij kod SMS'));
    await settle(tester);
    expect(server.sent('POST /api/auth/request-code').single.body, {'phone': '+48511200002', 'purpose': 'login'});
    expect(find.text('Wpisz kod z SMS-a'), findsOneWidget);
    expect(find.textContaining('+48 511 200 002', findRichText: true), findsOneWidget);
    expect(find.text('Nowy kod możesz dostać za 1:00.'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '123456');
    await settle(tester);
    expect(server.sent('POST /api/auth/verify-code').single.body, {'phone': '+48511200002', 'code': '123456'});
    expect(container.read(prefsProvider).get(Prefs.sessionKey), 'fresh');
    expect(find.text('Mój grafik'), findsWidgets);
    expect(find.text('Kiedy mogę'), findsOneWidget);
    expect(find.text('Powiadomienia'), findsOneWidget);
  });

  testWidgets('a wrong code says what the server said', (tester) async {
    final server = FakeServer()
      ..on('GET /api/me', (_) => const Reply(401))
      ..on(
        'POST /api/auth/request-code',
        (_) => const Reply(200, {'phone': '+48511200002', 'expires_in_s': 600, 'resend_after_s': 0}),
      )
      ..on('POST /api/auth/verify-code', (_) => const Reply(400, {'detail': 'Kod jest nieprawidłowy.'}));
    await pumpApp(tester, server);
    await tester.enterText(find.byType(TextField), '511200002');
    await tester.tap(find.text('Wyślij kod SMS'));
    await settle(tester);
    await tester.enterText(find.byType(TextField), '000000');
    await settle(tester);
    expect(find.text('Kod jest nieprawidłowy.'), findsOneWidget);
    expect(find.text('Wyślij kod jeszcze raz'), findsOneWidget);
  });

  testWidgets('an ended session sends the person to login and says why', (tester) async {
    final server = FakeServer()..on('GET /api/me', (_) => const Reply(401, {'detail': 'Zaloguj się.'}));
    await pumpApp(tester, server, stored: {Prefs.sessionKey: 'expired'});
    expect(find.text('Zaloguj się'), findsOneWidget);
    expect(find.text('Sesja wygasła. Zaloguj się jeszcze raz. To, co już zapisane, zostało.'), findsOneWidget);
  });

  testWidgets('a person without a company accepts an invitation and gets the tabs', (tester) async {
    var accepted = false;
    final server = FakeServer()
      ..on('GET /api/me', (_) => Reply(200, accepted ? meJson() : meJson(companies: [], pendingInvitations: 1)))
      ..on(
        'GET /api/me/invitations',
        (_) => Reply(200, [
          if (!accepted)
            {
              'id': 'i1',
              'company_name': 'Piekarnia Pod Lipą',
              'location_name': 'Lipowa',
              'location_address': 'ul. Lipowa 1',
              'role': 'employee',
              'invited_by_name': 'Ewa Malinowska',
              'created_at': '2026-11-27T10:00:00Z',
            },
        ]),
      )
      ..on('POST /api/invitations/i1/accept', (_) {
        accepted = true;
        return const Reply(200, {
          'id': 'i1',
          'company_name': 'Piekarnia Pod Lipą',
          'location_name': 'Lipowa',
          'location_address': 'ul. Lipowa 1',
          'role': 'employee',
          'invited_by_name': 'Ewa Malinowska',
          'created_at': '2026-11-27T10:00:00Z',
        });
      });
    await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'});
    expect(find.text('Zaproszenia do pracy'), findsOneWidget);
    expect(find.text('Ewa Malinowska'), findsOneWidget);
    await tester.tap(find.text('Przyjmij zaproszenie'));
    await settle(tester);
    expect(find.text('Mój grafik'), findsWidgets);
  });

  testWidgets('a person with no company and no invitation learns where companies are set up', (tester) async {
    final server = FakeServer()
      ..on('GET /api/me', (_) => Reply(200, meJson(companies: [])))
      ..on('GET /api/me/invitations', (_) => const Reply(200, []));
    await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'});
    expect(find.text('Nie masz żadnych zaproszeń'), findsOneWidget);
    expect(find.text('Prowadzisz lokal? Firmę założysz na stronie Grafikomatu.'), findsOneWidget);
    expect(find.text('Wróć do grafiku'), findsNothing);
  });

  testWidgets('a person who already works somewhere can leave an invitation for later', (tester) async {
    final server = FakeServer()
      ..on('GET /api/me', (_) => Reply(200, meJson(pendingInvitations: 1)))
      ..on(
        'GET /api/me/invitations',
        (_) => const Reply(200, [
          {
            'id': 'i2',
            'company_name': 'Kawiarnia Pod Lipami',
            'location_name': 'Kazimierz',
            'location_address': 'ul. Szeroka 2',
            'role': 'employee',
            'invited_by_name': 'Rafał Kubacki',
            'created_at': '2026-11-27T10:00:00Z',
          },
        ]),
      );
    await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'});
    expect(find.text('Zaproszenia do pracy'), findsOneWidget);
    await tester.tap(find.text('Wróć do grafiku'));
    await settle(tester);
    expect(find.text('Mój grafik'), findsWidgets);
    expect(find.text('Masz nowe zaproszenie do pracy. Zobacz'), findsOneWidget);
  });

  testWidgets('"Twoje dane" saves the name and sends the account number only when it changed', (tester) async {
    final server = FakeServer()
      ..on('GET /api/me', (_) => Reply(200, meJson(bankAccount: '12 3456')))
      ..on('PATCH /api/me', (sent) => Reply(200, meJson(firstName: 'Aleksandra', bankAccount: '12 3456')));
    await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'});
    await tester.tap(find.byTooltip('Twoje dane'));
    await settle(tester);
    expect(find.text('Logujesz się numerem +48 511 200 002.'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Imię'), 'Aleksandra');
    await tester.tap(find.text('Zapisz dane'));
    await settle(tester);
    expect(server.sent('PATCH /api/me').single.body, {'first_name': 'Aleksandra', 'last_name': 'Nowak'});
    expect(find.text('Zapisane'), findsOneWidget);
  });

  testWidgets('"Wyloguj" that does not reach the server keeps the person logged in and says so', (tester) async {
    final server = FakeServer()
      ..on('GET /api/me', (_) => Reply(200, meJson()))
      ..on('POST /api/auth/logout', (_) => const Reply(503));
    await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'});
    await tester.tap(find.byTooltip('Twoje dane'));
    await settle(tester);
    await tester.tap(find.text('Wyloguj'));
    await settle(tester);
    expect(find.text('Nie udało się wylogować. Sesja trwa dalej. Sprawdź internet.'), findsOneWidget);
    expect(find.text('Twoje dane'), findsWidgets);
  });

  testWidgets('"Wyloguj" ends the session and opens the login screen', (tester) async {
    var loggedIn = true;
    final server = FakeServer()
      ..on('GET /api/me', (_) => loggedIn ? Reply(200, meJson()) : const Reply(401))
      ..on('POST /api/auth/logout', (_) {
        loggedIn = false;
        return const Reply(204, null, {'X-Grafikomat-Session': ''});
      });
    final container = await pumpApp(tester, server, stored: {Prefs.sessionKey: 'k'});
    await tester.tap(find.byTooltip('Twoje dane'));
    await settle(tester);
    await tester.tap(find.text('Wyloguj'));
    await settle(tester);
    expect(find.text('Zaloguj się'), findsOneWidget);
    expect(container.read(prefsProvider).get(Prefs.sessionKey), isNull);
  });
}
