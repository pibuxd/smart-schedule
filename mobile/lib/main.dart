import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import 'api/client.dart';
import 'api/errors.dart';
import 'app.dart';
import 'session/prefs.dart';

/// Grafikomat on the phone (docs/mobile.md). The stored login is read before the first screen, so a restarted app
/// opens logged in.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await Prefs.load(const SecureStore());
  runApp(
    ProviderScope(overrides: [prefsProvider.overrideWithValue(prefs)], retry: retryDelay, child: const GrafikomatApp()),
  );
}
