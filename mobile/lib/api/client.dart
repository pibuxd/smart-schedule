import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../session/prefs.dart';
import '../session/session.dart';
import 'config.dart';
import 'generated/grafikomat_api.dart';

/// Every request says it comes from the app (`ios`, `android`; `web` only in the browser preview) and carries the
/// session key instead of a cookie (backend `apps/core/native.py`). The server hands a new key (login) or an empty
/// one (logout, ended session) back in the same header.
const clientHeader = 'X-Grafikomat-Client';
const sessionHeader = 'X-Grafikomat-Session';

String clientPlatform() {
  if (kIsWeb) return 'web';
  return switch (defaultTargetPlatform) {
    TargetPlatform.iOS => 'ios',
    TargetPlatform.android => 'android',
    _ => 'app',
  };
}

class SessionInterceptor extends Interceptor {
  SessionInterceptor(this._prefs, {required this.onSessionEnded});

  final Prefs _prefs;

  /// A request made with a session key was refused with 401: the session ended (logged out elsewhere, expired,
  /// number changed by the superadmin).
  final void Function(String path) onSessionEnded;

  static const _hadSession = 'grafikomat.had-session';

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    options.headers[clientHeader] = clientPlatform();
    final key = _prefs.get(Prefs.sessionKey);
    if (key != null) options.headers[sessionHeader] = key;
    options.extra[_hadSession] = key != null;
    handler.next(options);
  }

  @override
  void onResponse(Response<dynamic> response, ResponseInterceptorHandler handler) {
    _takeKey(response);
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final response = err.response;
    if (response != null) {
      _takeKey(response);
      if (response.statusCode == 401 && err.requestOptions.extra[_hadSession] == true) {
        // The key is worth nothing now, even if the server did not say so in the header.
        _prefs.set(Prefs.sessionKey, null);
        onSessionEnded(err.requestOptions.path);
      }
    }
    handler.next(err);
  }

  void _takeKey(Response<dynamic> response) {
    final handed = response.headers.value(sessionHeader);
    if (handed != null) _prefs.set(Prefs.sessionKey, handed.isEmpty ? null : handed);
  }
}

/// The values read from secure storage at start (`main.dart` overrides it).
final prefsProvider = Provider<Prefs>((ref) => throw UnimplementedError('Prefs are loaded in main()'));

/// Set when a request found the session ended, so the login screen can say why the person is there.
class SessionEnded extends Notifier<bool> {
  @override
  bool build() => false;

  void mark() => state = true;

  /// The login screen said it; the next visit to it is a plain login.
  void clear() => state = false;
}

final sessionEndedProvider = NotifierProvider<SessionEnded, bool>(SessionEnded.new);

/// The server's address (built into the app; tests give their own).
final apiOriginProvider = Provider<String>((ref) => apiOrigin());

/// Tests answer requests themselves (`test/helpers.dart`); the app uses Dio's own connection.
final httpAdapterProvider = Provider<HttpClientAdapter?>((ref) => null);

final Provider<Dio> dioProvider = Provider<Dio>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: ref.watch(apiOriginProvider),
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 60),
    ),
  );
  dio.interceptors.add(
    SessionInterceptor(
      ref.watch(prefsProvider),
      onSessionEnded: (path) {
        ref.read(sessionEndedProvider.notifier).mark();
        // Ask again who is logged in: nobody, so the router opens the login screen. Not from inside the very read
        // of who is logged in (it answers "nobody" by itself), and not in the middle of another provider's work.
        if (path != '/api/me') Future.microtask(() => ref.invalidate(meProvider));
      },
    ),
  );
  final adapter = ref.watch(httpAdapterProvider);
  if (adapter != null) dio.httpClientAdapter = adapter;
  return dio;
});

/// The generated API client (`swagger_parser.yaml`), one per app.
final Provider<GrafikomatApi> apiProvider = Provider<GrafikomatApi>((ref) => GrafikomatApi(ref.watch(dioProvider)));
