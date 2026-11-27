/// Where the app finds the API: the server's address, fixed when the app is built
/// (`--dart-define-from-file=config/local.json`, key `API_ORIGIN`, e.g. "https://grafikomat.pl"; see docs/mobile.md).
/// A release build must use https; while developing, a phone may call a computer on the same network over http.
library;

const String _origin = String.fromEnvironment('API_ORIGIN');

String apiOrigin() => _origin.replaceAll(RegExp(r'/+$'), '');

/// What is wrong with the address, or null. A store build without an https address cannot work.
String? apiOriginProblem(String origin, {required bool release}) {
  if (origin.isEmpty) return 'Aplikacja nie zna adresu serwera. Zbuduj ją z adresem w API_ORIGIN.';
  if (release && !origin.startsWith('https://')) return 'Adres serwera w aplikacji musi zaczynać się od https://.';
  return null;
}
