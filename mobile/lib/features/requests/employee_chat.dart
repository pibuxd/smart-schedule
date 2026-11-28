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
/// and the unsent message of every conversation. A new login starts it afresh.
class EmployeeChatMemory {
  ChatScope? screen;
  final Map<String, String> drafts = {};
}

final employeeChatMemoryProvider = Provider<EmployeeChatMemory>((ref) {
  ref.watch(sessionProvider.select((session) => session is SessionReady ? session.me.id : null));
  return EmployeeChatMemory();
});

/// Opens the employee's chat as a page of its own, over the tabs: on [scope] when given (from "Twoje prośby"), else on
/// [screen] (the month of "Kiedy mogę" when that tab is open), else on the period the manager asked for, or this month
/// before that.
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
        ? ChatScope(periodId: period.id, editable: true)
        : ChatScope(month: '${monthOf(toIsoDate(today))}-01', editable: true);
    final scope = data == null ? null : asked ?? (screen?.editable == true ? screen : null) ?? nearest;
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
              draft: memory.drafts[scope.key] ?? '',
              onDraftChanged: (text) => memory.drafts[scope.key] = text,
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
