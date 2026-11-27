import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/api/client.dart';
import 'package:grafikomat/api/errors.dart';
import 'package:grafikomat/api/generated/exports.dart';
import 'package:grafikomat/router.dart';
import 'package:grafikomat/session/prefs.dart';
import 'package:grafikomat/session/session.dart';

import 'helpers.dart';

Future<ProviderContainer> container(FakeServer server, {Map<String, String>? stored}) async {
  final prefs = await Prefs.load(MemoryStore(stored));
  final c = ProviderContainer(
    overrides: [
      prefsProvider.overrideWithValue(prefs),
      apiOriginProvider.overrideWithValue('https://grafikomat.test'),
      httpAdapterProvider.overrideWithValue(server),
    ],
    retry: (_, _) => null,
  );
  addTearDown(c.dispose);
  return c;
}

void main() {
  group('the session key in a header', () {
    test('every request says it is the app and carries the stored key', () async {
      final server = FakeServer()..on('GET /api/me', (_) => Reply(200, meJson()));
      final c = await container(server, stored: {Prefs.sessionKey: 'k1'});
      await c.read(meProvider.future);
      final sent = server.requests.single;
      expect(sent.headers['X-Grafikomat-Client'], isNotNull);
      expect(sent.headers['X-Grafikomat-Session'], 'k1');
    });

    test('keeps the key the server hands over and forgets an emptied one', () async {
      final server = FakeServer()
        ..on('POST /api/auth/verify-code', (_) => Reply(200, meJson(), {'X-Grafikomat-Session': 'new-key'}))
        ..on('POST /api/auth/logout', (_) => const Reply(204, null, {'X-Grafikomat-Session': ''}));
      final c = await container(server);
      final api = c.read(apiProvider);
      await api.auth.verifyCode(
        body: const VerifyCodeIn(phone: '+48511200002', code: '123456'),
      );
      expect(c.read(prefsProvider).get(Prefs.sessionKey), 'new-key');
      await api.auth.logout();
      expect(c.read(prefsProvider).get(Prefs.sessionKey), isNull);
    });

    test('a 401 with a key means the session ended: the key goes and the login screen will say why', () async {
      final server = FakeServer()..on('GET /api/me', (_) => const Reply(401, {'detail': 'Zaloguj się.'}));
      final c = await container(server, stored: {Prefs.sessionKey: 'old'});
      expect(await c.read(meProvider.future), isNull);
      expect(c.read(prefsProvider).get(Prefs.sessionKey), isNull);
      expect(c.read(sessionEndedProvider), isTrue);
    });

    test('a 401 without a key is just being logged out', () async {
      final server = FakeServer()..on('GET /api/me', (_) => const Reply(401, {'detail': 'Zaloguj się.'}));
      final c = await container(server);
      expect(await c.read(meProvider.future), isNull);
      expect(c.read(sessionEndedProvider), isFalse);
      expect(c.read(sessionProvider), isA<SessionLoggedOut>());
    });
  });

  test('shows the chosen company, else the first one', () async {
    final companies = [
      {'id': 'c1', 'name': 'Piekarnia', 'role': 'employee', 'read_only': false},
      {'id': 'c2', 'name': 'Kawiarnia', 'role': 'manager', 'read_only': false},
    ];
    final server = FakeServer()..on('GET /api/me', (_) => Reply(200, meJson(companies: companies)));
    final c = await container(server, stored: {Prefs.companyKey: 'c2'});
    await c.read(meProvider.future);
    final session = c.read(sessionProvider) as SessionReady;
    expect(session.company!.name, 'Kawiarnia');
    expect(session.isManager, isTrue);
    c.read(companyChoiceProvider.notifier).choose('c1');
    expect((c.read(sessionProvider) as SessionReady).company!.name, 'Piekarnia');
    expect(c.read(prefsProvider).get(Prefs.companyKey), 'c1');
  });

  group('where the router sends the person', () {
    final me = MeOut.fromJson(meJson());
    final company = me.companies.first;

    test('logged out: only the login screen', () {
      expect(sessionRedirect(const SessionLoggedOut(), Uri.parse('/grafik?dzien=2026-12-01')), '/logowanie');
      expect(sessionRedirect(const SessionLoggedOut(), Uri.parse('/logowanie')), isNull);
    });

    test('logged in: the schedule, or invitations when one waits or there is no company', () {
      expect(sessionRedirect(SessionReady(me, company), Uri.parse('/logowanie')), '/grafik');
      expect(sessionRedirect(SessionReady(me, company), Uri.parse('/')), '/grafik');
      expect(sessionRedirect(SessionReady(me, company), Uri.parse('/kiedy-moge')), isNull);
      final invited = MeOut.fromJson(meJson(pendingInvitations: 1));
      expect(sessionRedirect(SessionReady(invited, company), Uri.parse('/')), '/zaproszenia');
      final alone = MeOut.fromJson(meJson(companies: []));
      expect(sessionRedirect(SessionReady(alone, null), Uri.parse('/grafik')), '/zaproszenia');
      expect(sessionRedirect(SessionReady(alone, null), Uri.parse('/twoje-dane')), isNull);
    });

    test('while loading nothing moves, so a link that opened the app stays', () {
      expect(sessionRedirect(const SessionLoading(), Uri.parse('/grafik?dzien=2026-12-01')), isNull);
    });
  });

  group('error messages', () {
    test('a restarting server is asked again, a final answer is not', () {
      expect(retryDelay(0, Exception('not dio')), isNull);
    });
    test('network problems keep the fallback', () {
      expect(errorMessage(Exception('offline'), networkProblem), networkProblem);
    });
  });
}
