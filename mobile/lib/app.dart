import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import 'api/client.dart';
import 'api/config.dart';
import 'router.dart';
import 'ui/status.dart';
import 'ui/theme.dart';

const _polish = [Locale('pl', 'PL')];

class GrafikomatApp extends ConsumerWidget {
  const GrafikomatApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final problem = apiOriginProblem(ref.watch(apiOriginProvider), release: kReleaseMode);
    if (problem != null) {
      // A build without the server's address must say so instead of failing on every screen.
      return MaterialApp(
        title: 'Grafikomat',
        theme: appTheme(),
        locale: _polish.first,
        supportedLocales: _polish,
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: Scaffold(
          body: SafeArea(
            child: Padding(padding: const EdgeInsets.all(gutter), child: ErrorView(problem)),
          ),
        ),
      );
    }
    return MaterialApp.router(
      title: 'Grafikomat',
      theme: appTheme(),
      locale: _polish.first,
      supportedLocales: _polish,
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      debugShowCheckedModeBanner: false,
      routerConfig: ref.watch(routerProvider),
    );
  }
}
