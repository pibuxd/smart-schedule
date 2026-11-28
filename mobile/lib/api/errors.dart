/// Errors of API calls in plain Polish, the same words as the website (`frontend/src/lib/api-error.ts`).
/// The generated client throws `DioException`; an answer from the server carries its status and body.
library;

import 'package:dio/dio.dart';

const networkProblem = 'Nie udało się połączyć z serwerem. Sprawdź internet i spróbuj jeszcze raz.';

const serverProblem = 'To błąd po naszej stronie, nie Twojego internetu. Spróbuj za chwilę jeszcze raz.';

/// The HTTP status the server answered with, or null when there was no answer (no internet, timeout).
int? errorStatus(Object? error) => error is DioException ? error.response?.statusCode : null;

/// The Polish message the API sent (`{"detail": ...}`). When the server answered without one (a crash, a proxy
/// error), the problem is on our side, so the person is not sent to check the internet. The fallback is for
/// network problems.
String errorMessage(Object? error, String fallback) {
  if (error is DioException && error.response != null) {
    final body = error.response!.data;
    if (body is Map && body['detail'] is String) return body['detail'] as String;
    if ((error.response!.statusCode ?? 0) >= 500) return _serverProblem(fallback);
  }
  return fallback;
}

/// "Nie udało się wczytać grafiku. Sprawdź internet…" becomes "Nie udało się wczytać grafiku." plus [serverProblem].
String _serverProblem(String fallback) {
  if (fallback.startsWith('Nie udało się połączyć')) return serverProblem;
  final end = fallback.indexOf('. ');
  return end > 0 ? '${fallback.substring(0, end + 1)} $serverProblem' : serverProblem;
}

/// Whether a failed read is worth asking again, and after how long: lost connections and a restarting server
/// (502/503/504) up to four times with growing pauses, other server errors once. An answer such as 404 or 409 is
/// final. Used as Riverpod's retry for every read.
Duration? retryDelay(int retryCount, Object error) {
  final status = errorStatus(error);
  final again = (status == null || status == 502 || status == 503 || status == 504)
      ? retryCount < 4
      : status >= 500 && retryCount < 1;
  if (!again || (error is! DioException)) return null;
  return Duration(milliseconds: 500 * (1 << retryCount));
}
