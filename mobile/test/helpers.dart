import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/api/client.dart';
import 'package:grafikomat/app.dart';
import 'package:grafikomat/session/prefs.dart';

/// One answer of the fake server.
class Reply {
  const Reply(this.status, [this.body, this.headers = const {}]);

  final int status;
  final Object? body;
  final Map<String, String> headers;
}

/// A request the app sent, as the fake server saw it.
class Sent {
  Sent(this.method, this.path, this.headers, this.body);

  final String method;
  final String path;
  final Map<String, dynamic> headers;
  final Object? body;
}

/// Answers the app's API calls in tests: `on('GET /api/me', (sent) => Reply(200, {...}))`. A call nobody answers
/// fails the test with its address.
class FakeServer implements HttpClientAdapter {
  final _routes = <String, Reply Function(Sent sent)>{};
  final List<Sent> requests = [];

  void on(String route, Reply Function(Sent sent) reply) => _routes[route] = reply;

  Iterable<Sent> sent(String route) => requests.where((r) => '${r.method} ${r.path}' == route);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    Object? body;
    if (options.data is String) body = jsonDecode(options.data as String);
    final sent = Sent(options.method, options.uri.path, Map.of(options.headers), body);
    requests.add(sent);
    final route = '${options.method} ${options.uri.path}';
    final handler = _routes[route];
    if (handler == null) fail('Nothing answers $route');
    final reply = handler(sent);
    return ResponseBody.fromString(
      reply.body == null ? '' : jsonEncode(reply.body),
      reply.status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
        for (final entry in reply.headers.entries) entry.key.toLowerCase(): [entry.value],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Map<String, Object?> meJson({
  String firstName = 'Ola',
  String lastName = 'Nowak',
  List<Map<String, Object?>>? companies,
  int pendingInvitations = 0,
  String bankAccount = '',
}) => {
  'id': 'u1',
  'phone': '+48511200002',
  'first_name': firstName,
  'last_name': lastName,
  'bank_account': bankAccount,
  'companies':
      companies ??
      [
        {'id': 'c1', 'name': 'Piekarnia Pod Lipą', 'role': 'employee', 'read_only': false, 'works_shifts': true},
      ],
  'pending_invitations': pendingInvitations,
};

/// The whole app with its router, talking to [server]; [stored] is what secure storage holds at start.
Future<ProviderContainer> pumpApp(WidgetTester tester, FakeServer server, {Map<String, String>? stored}) async {
  final prefs = await Prefs.load(MemoryStore(stored));
  final container = ProviderContainer(
    overrides: [
      prefsProvider.overrideWithValue(prefs),
      apiOriginProvider.overrideWithValue('https://grafikomat.test'),
      httpAdapterProvider.overrideWithValue(server),
    ],
    retry: (_, _) => null,
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const GrafikomatApp()));
  await settle(tester);
  return container;
}

/// Lets requests answer and screens change. Spinners never stop, so `pumpAndSettle` would wait forever.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}
