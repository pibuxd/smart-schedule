import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../../session/session.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../auth/profile_name_form.dart';

/// The employee's tabs at the bottom (thumb reach): "Mój grafik", "Kiedy mogę", "Powiadomienia". Each tab keeps its
/// own place when the person switches between them. The assistant becomes the fourth tab in a later stage.
class EmployeeShell extends StatelessWidget {
  const EmployeeShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  static const tabs = [
    (label: 'Mój grafik', icon: Icons.calendar_month_outlined, selected: Icons.calendar_month),
    (label: 'Kiedy mogę', icon: Icons.event_available_outlined, selected: Icons.event_available),
    (label: 'Powiadomienia', icon: Icons.notifications_outlined, selected: Icons.notifications),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: shell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: shell.currentIndex,
        // Tapping the open tab again goes back to its first screen.
        onDestinationSelected: (index) => shell.goBranch(index, initialLocation: index == shell.currentIndex),
        destinations: [
          for (final tab in tabs)
            NavigationDestination(icon: Icon(tab.icon), selectedIcon: Icon(tab.selected), label: tab.label),
        ],
      ),
    );
  }
}

/// One tab's screen: its title with "Twoje dane" at the top right, then the notes every tab shows (the name to
/// fill in, a new invitation) and the tab's content. Pull down to refresh.
class TabScreen extends ConsumerWidget {
  const TabScreen({super.key, required this.title, required this.children, this.onRefresh});

  final String title;
  final List<Widget> children;
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    if (session is! SessionReady) {
      return Scaffold(
        appBar: AppBar(title: Text(title)),
        body: switch (session) {
          SessionError() => Padding(
            padding: const EdgeInsets.all(gutter),
            child: ErrorView(
              'Nie udało się otworzyć Grafikomatu. Sprawdź internet i spróbuj jeszcze raz.',
              onRetry: () => ref.invalidate(meProvider),
            ),
          ),
          _ => const Center(child: LoadingView('Otwieram Grafikomat…')),
        },
      );
    }
    final company = session.company;
    final list = ListView(
      padding: const EdgeInsets.fromLTRB(gutter, 8, gutter, 32),
      children: [
        if (session.me.firstName.isEmpty) ...[ProfileNameForm(me: session.me), const SizedBox(height: 16)],
        if (session.me.pendingInvitations > 0) ...[
          OutlinedButton(
            onPressed: () => context.push('/zaproszenia'),
            child: const Text('Masz nowe zaproszenie do pracy. Zobacz'),
          ),
          const SizedBox(height: 16),
        ],
        ...children,
      ],
    );
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title),
            if (company != null && session.me.companies.length > 1)
              Text(
                company.name,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w400, color: AppColors.inkMuted),
              ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Twoje dane',
            icon: const Icon(Icons.account_circle_outlined),
            onPressed: () => context.push('/twoje-dane'),
          ),
        ],
      ),
      body: onRefresh == null ? list : RefreshIndicator.adaptive(onRefresh: onRefresh!, child: list),
    );
  }
}
