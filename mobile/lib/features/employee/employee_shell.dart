import 'dart:math' as math;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../../session/session.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../auth/profile_name_form.dart';
import '../availability/availability_data.dart';
import '../requests/employee_chat.dart';

/// The employee's tabs at the bottom (thumb reach): "Mój grafik", "Kiedy mogę", "Powiadomienia", and the assistant's
/// chat as the last one. Each tab keeps its own place when the person switches between them; the chat opens over them
/// as a page of its own. While the company's access has expired there is no chat.
class EmployeeShell extends ConsumerWidget {
  const EmployeeShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  static const tabs = [
    (label: 'Mój grafik', icon: Icons.calendar_month_outlined, selected: Icons.calendar_month),
    (label: 'Kiedy mogę', icon: Icons.event_available_outlined, selected: Icons.event_available),
    (label: 'Powiadomienia', icon: Icons.notifications_outlined, selected: Icons.notifications),
  ];

  /// "Kiedy mogę": while it is open, the chat talks about the month on screen.
  static const availabilityTab = 1;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final company = session is SessionReady ? session.company : null;
    final chat = company != null && !company.readOnly;
    final assistantReads = !chat || assistantReadsOf(ref.watch(myAvailabilityProvider(company.id)));
    return Scaffold(
      body: shell,
      bottomNavigationBar: LayoutBuilder(
        builder: (context, box) {
          final labels = [for (final tab in tabs) tab.label, if (chat) assistantReads ? 'Asystent' : 'Prośby'];
          return MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: tabLabelScaler(context, labels, box.maxWidth)),
            child: NavigationBar(
              selectedIndex: shell.currentIndex,
              onDestinationSelected: (index) {
                if (index == tabs.length) {
                  final screen = ref.read(employeeChatMemoryProvider).screen;
                  openEmployeeChat(context, ref, screen: shell.currentIndex == availabilityTab ? screen : null);
                  return;
                }
                // Tapping the open tab again goes back to its first screen.
                shell.goBranch(index, initialLocation: index == shell.currentIndex);
              },
              destinations: [
                for (final tab in tabs)
                  NavigationDestination(icon: Icon(tab.icon), selectedIcon: Icon(tab.selected), label: tab.label),
                if (chat)
                  NavigationDestination(
                    icon: const Icon(Icons.chat_bubble_outline),
                    label: assistantReads ? 'Asystent' : 'Prośby',
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// One tab's screen: its title with "Twoje dane" at the top right, then the notes every tab shows (the name to
/// fill in, a new invitation) and the tab's content. Pull down to refresh. [bottom] stays at the foot of the screen
/// above the tabs while the content scrolls.
class TabScreen extends ConsumerWidget {
  const TabScreen({super.key, required this.title, required this.children, this.onRefresh, this.bottom});

  final String title;
  final List<Widget> children;
  final Future<void> Function()? onRefresh;
  final Widget? bottom;

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
    // One column, not a lazy list: a tapped notification scrolls to a row far down, which must already exist.
    final list = SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(gutter, 8, gutter, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
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
      ),
    );
    final appBar = AppBar(
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
    );
    final body = onRefresh == null ? list : RefreshIndicator.adaptive(onRefresh: onRefresh!, child: list);
    return Scaffold(
      appBar: appBar,
      body: bottom == null
          ? body
          : Column(
              children: [
                Expanded(child: body),
                bottom!,
              ],
            ),
    );
  }
}

/// The tab labels grow with the phone's text size, but only as far as the longest one ("Powiadomienia") still fits
/// its tab, so no label breaks in the middle of a word on a narrow phone. Never below the normal size.
TextScaler tabLabelScaler(BuildContext context, List<String> labels, double width) {
  final scaler = MediaQuery.textScalerOf(context);
  if (labels.isEmpty || !width.isFinite) return scaler;
  final style =
      Theme.of(context).navigationBarTheme.labelTextStyle?.resolve({WidgetState.selected}) ??
      const TextStyle(fontSize: 12);
  var widest = 0.0;
  for (final label in labels) {
    final painter = TextPainter(
      text: TextSpan(text: label, style: style),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout();
    widest = math.max(widest, painter.width);
    painter.dispose();
  }
  // Each tab gets an equal share of the bar; a little room stays at its edges.
  final room = width / labels.length - 8;
  return scaler.clamp(maxScaleFactor: widest == 0 ? double.infinity : math.max(1.0, room / widest));
}
