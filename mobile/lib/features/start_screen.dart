import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../api/errors.dart';
import '../session/session.dart';
import '../ui/status.dart';
import '../ui/theme.dart';
import '../ui/wordmark.dart';

/// The first screen while the app asks who is logged in; the router then opens login, invitations or the schedule.
class StartScreen extends ConsumerWidget {
  const StartScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(gutter),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Wordmark(),
              const Spacer(),
              if (session is SessionError)
                ErrorView(errorMessage(session.error, networkProblem), onRetry: () => ref.invalidate(meProvider))
              else
                const LoadingView('Otwieram Grafikomat…'),
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}
