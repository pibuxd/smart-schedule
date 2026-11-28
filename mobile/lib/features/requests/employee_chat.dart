import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../shared/dates.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../availability/availability_data.dart';
import '../schedule/schedule_data.dart';
import 'request_words.dart';
import 'requests_chat.dart';
import 'requests_data.dart';

/// What the chat keeps while the app is open: the conversation of the screen on view ("Kiedy mogę" sets its month)
/// and the unsent message of every conversation (by [ChatScope.key], so per company too). A new login starts it
/// afresh.
class EmployeeChatMemory {
  ChatScope? screen;
  final Map<String, TextEditingController> _drafts = {};

  /// The field's text of one conversation. It outlives the chat page, so a message sent just before the chat was
  /// closed still clears it once the server took the message.
  TextEditingController draft(ChatScope scope) => _drafts.putIfAbsent(scope.key, TextEditingController.new);

  void dispose() {
    for (final draft in _drafts.values) {
      draft.dispose();
    }
  }
}

final employeeChatMemoryProvider = Provider<EmployeeChatMemory>((ref) {
  ref.watch(sessionProvider.select((session) => session is SessionReady ? session.me.id : null));
  final memory = EmployeeChatMemory();
  ref.onDispose(memory.dispose);
  return memory;
});

/// Opens the employee's chat as a page of its own, over the tabs: on [scope] when given (from "Twoje prośby"), else on
/// [screen] (the month of "Kiedy mogę" when that tab is open, also a closed one: its history, to read), else on the
/// period the manager asked for, or this month before that.
Future<void> openEmployeeChat(BuildContext context, WidgetRef ref, {ChatScope? scope, ChatScope? screen}) {
  final session = ref.read(sessionProvider);
  final company = session is SessionReady ? session.company : null;
  // The manager may have asked for a period since the app was opened.
  if (company != null) ref.invalidate(myAvailabilityProvider(company.id));
  return Navigator.of(context, rootNavigator: true).push(
    MaterialPageRoute<void>(
      builder: (_) => EmployeeChatPage(asked: scope, screen: screen),
    ),
  );
}

/// The tab's label and the chat's name: "Asystent" when the assistant reads messages (the usual case, also until the
/// server answers), else "Prośby".
bool assistantReadsOf(AsyncValue<MyAvailabilityOut> availability) => availability.value?.assistantReads ?? true;

class EmployeeChatPage extends ConsumerWidget {
  const EmployeeChatPage({super.key, this.asked, this.screen});

  final ChatScope? asked;
  final ChatScope? screen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final company = session is SessionReady ? session.company : null;
    if (company == null) return Scaffold(appBar: AppBar());
    final availability = ref.watch(myAvailabilityProvider(company.id));
    final data = availability.value;
    final assistantReads = assistantReadsOf(availability);
    final today = ref.read(clockProvider)();
    final period = data?.period;
    final nearest = period != null && period.editable
        ? ChatScope(companyId: company.id, periodId: period.id, editable: true)
        : ChatScope(companyId: company.id, month: '${monthOf(toIsoDate(today))}-01', editable: true);
    // The conversation on screen, as "Pokaż rozmowę" there opens it; [ChatScope.editable] decides what can be written.
    final onScreen = screen?.companyId == company.id ? screen : null;
    final scope = data == null ? null : (asked?.companyId == company.id ? asked : null) ?? onScreen ?? nearest;
    final subtitle =
        (scope == null ? null : scopeLine(scope, period)) ??
        (assistantReads ? 'Zapytaj o swój grafik albo napisz prośbę.' : 'Napisz prośbę do kierownika.');
    final memory = ref.watch(employeeChatMemoryProvider);

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(assistantReads ? 'Asystent' : 'Prośby do kierownika'),
            Text(
              subtitle,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w400, color: AppColors.inkMuted),
            ),
          ],
        ),
        actions: [
          if (scope != null)
            IconButton(
              tooltip: 'O prośbach i Twoich danych',
              icon: const Icon(Icons.info_outline),
              onPressed: () =>
                  showAboutRequests(context, assistantReads: assistantReads, month: scope.periodId == null),
            ),
        ],
      ),
      body: scope != null
          ? RequestsChat(
              key: ValueKey(scope.key),
              companyId: company.id,
              scope: scope,
              assistantReads: assistantReads,
              only: onlyWords(scope, period),
              draft: memory.draft(scope),
              readOnly: company.readOnly,
            )
          : availability.hasError
          ? Padding(
              padding: const EdgeInsets.all(gutter),
              child: ErrorView(
                'Nie udało się otworzyć rozmowy. Sprawdź internet i spróbuj jeszcze raz.',
                onRetry: () => ref.invalidate(myAvailabilityProvider(company.id)),
              ),
            )
          : const LoadingView('Otwieram rozmowę…'),
    );
  }
}
