import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/errors.dart';
import 'prefs.dart';
import 'session.dart';

/// "Wyloguj": the server ends the session (and unpins this phone from push). Only a confirmed logout logs out here
/// too: when the request fails (no internet, a server error), the key stays, the person stays logged in and the
/// screen says so. A 401 means the session had ended already, which is a logout as well.
///
/// Returns true when logged out.
Future<bool> signOut(WidgetRef ref) async {
  try {
    await ref.read(apiProvider).auth.logout();
  } catch (error) {
    if (errorStatus(error) != 401) return false;
  }
  ref.read(prefsProvider).set(Prefs.sessionKey, null);
  ref.invalidate(meProvider);
  return true;
}
