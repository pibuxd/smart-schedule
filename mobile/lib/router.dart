import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import 'features/auth/invitations_screen.dart';
import 'features/availability/availability_screen.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/my_data_screen.dart';
import 'features/employee/coming_screens.dart';
import 'features/employee/employee_shell.dart';
import 'features/schedule/my_schedule_screen.dart';
import 'features/start_screen.dart';
import 'session/session.dart';

/// The app's screens have the website's addresses (`/grafik`, `/kiedy-moge`, `/powiadomienia`, `/zaproszenia`), so
/// the screen a push notification names (backend `notifications.services.push_path`) opens here the same way.
///
/// Where the person may be, given who is logged in. Null = stay. While the session is loading or failed, every
/// screen stays and shows that state itself, so a link that opened the app is not lost.
String? sessionRedirect(Session session, Uri uri) {
  final path = uri.path;
  switch (session) {
    case SessionLoading() || SessionError():
      return null;
    case SessionLoggedOut():
      return path == '/logowanie' ? null : '/logowanie';
    case SessionReady(:final me, :final company):
      if (path == '/' || path == '/logowanie') {
        return me.pendingInvitations > 0 || company == null ? '/zaproszenia' : '/grafik';
      }
      // Someone without a company has only the invitations and their own data.
      if (company == null && path != '/zaproszenia' && path != '/twoje-dane') return '/zaproszenia';
      return null;
  }
}

final _isoDay = RegExp(r'^\d{4}-\d{2}-\d{2}$');
final _isoMonth = RegExp(r'^\d{4}-\d{2}$');
final _id = RegExp(r'^[\w-]{1,64}$');

/// `?dzien=2026-12-04` from a notification, or null for anything else.
String? searchDay(String? value) => value != null && _isoDay.hasMatch(value) ? value : null;

/// `?miesiac=2026-12` from a notification about that month's availability, or null for anything else.
String? searchMonth(String? value) => value != null && _isoMonth.hasMatch(value) ? value : null;

/// `?oferta=<id>`, `?okres=<id>`
String? searchId(String? value) => value != null && _id.hasMatch(value) ? value : null;

/// Tells the router to look again when the session changes (logged in, logged out, invitation accepted).
class _SessionListenable extends ChangeNotifier {
  void changed() => notifyListeners();
}

final routerProvider = Provider<GoRouter>((ref) {
  final listenable = _SessionListenable();
  ref.listen(sessionProvider, (_, _) => listenable.changed());
  ref.onDispose(listenable.dispose);
  return GoRouter(
    initialLocation: '/',
    refreshListenable: listenable,
    redirect: (context, state) => sessionRedirect(ref.read(sessionProvider), state.uri),
    routes: [
      GoRoute(path: '/', builder: (context, state) => const StartScreen()),
      GoRoute(path: '/logowanie', builder: (context, state) => const LoginScreen()),
      GoRoute(path: '/zaproszenia', builder: (context, state) => const InvitationsScreen()),
      GoRoute(path: '/twoje-dane', builder: (context, state) => const MyDataScreen()),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => EmployeeShell(shell: shell),
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/grafik',
                builder: (context, state) {
                  final day = searchDay(state.uri.queryParameters['dzien']);
                  final offer = searchId(state.uri.queryParameters['oferta']);
                  // A new notification opens the screen afresh on what it is about.
                  return ScheduleTab(key: ValueKey('${day ?? ''}/${offer ?? ''}'), focusDay: day, focusOffer: offer);
                },
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/kiedy-moge',
                builder: (context, state) {
                  final month = searchMonth(state.uri.queryParameters['miesiac']);
                  return AvailabilityTab(key: ValueKey(month ?? ''), month: month);
                },
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [GoRoute(path: '/powiadomienia', builder: (context, state) => const NotificationsTab())],
          ),
        ],
      ),
    ],
    // An address the app does not know (a manager's screen from a push, an old link): start over.
    onException: (context, state, router) => router.go('/'),
  );
});
