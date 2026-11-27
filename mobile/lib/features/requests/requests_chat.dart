import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'chat_parts.dart';
import 'request_status.dart';
import 'request_words.dart';
import 'requests_data.dart';

const _muted = TextStyle(fontSize: 14, color: AppColors.inkMuted);

/// The fine print of the chat, behind the "i" button at its top: what a request is, and who reads it.
String aboutRequests({required bool assistantReads, required bool month}) =>
    'W jednej wiadomości możesz zapytać o coś i napisać do trzech próśb. Napisz też powód, jeśli jest ważny. '
    'Dyspozycje zaznacz w kalendarzu. Prośba „Na stałe” liczy się też w kolejnych miesiącach, dopóki jej nie '
    'zakończysz w „Twoich prośbach”. '
    '${month ? 'Prośba dotyczy tego miesiąca. Kierownik weźmie ją pod uwagę, gdy będzie układać na niego grafik. ' : ''}'
    '${assistantReads ? 'Asystent AI (zewnętrzna usługa) czyta Twoją wiadomość, Twoje wcześniejsze prośby oraz imiona '
              'osób i nazwy zmian w lokalu. Żeby odpowiedzieć, sprawdza to, co widzisz w aplikacji: Twój grafik, '
              'wypłatę, dyspozycje, prośby, zmiany do wzięcia i powiadomienia. Nie dostaje numerów telefonów. Niczego '
              'nie zmienia sam: nie układa grafiku i nie zmienia kalendarza. Kierownik i jego asystent AI widzą Twoje '
              'dyspozycje, zapisane prośby (z pytaniami asystenta o nie) i to, co przekażesz kierownikowi. Reszty '
              'rozmowy nie widzą.' : 'Przeczyta to tylko kierownik.'}';

/// The conversation (the website's `RequestsChat`): every message with the assistant's answer, newest at the bottom,
/// and the field to write. The message being written lives outside ([draft], [onDraftChanged]), so leaving the chat
/// does not lose it.
class RequestsChat extends ConsumerStatefulWidget {
  const RequestsChat({
    super.key,
    required this.companyId,
    required this.scope,
    required this.assistantReads,
    required this.only,
    required this.draft,
    required this.onDraftChanged,
  });

  final String companyId;
  final ChatScope scope;
  final bool assistantReads;

  /// "w grudniu": the month (or days of the period) of this chat, for "Tylko w grudniu" / "Na stałe".
  final String only;
  final String draft;
  final ValueChanged<String> onDraftChanged;

  @override
  ConsumerState<RequestsChat> createState() => _RequestsChatState();
}

class _RequestsChatState extends ConsumerState<RequestsChat> {
  late final TextEditingController _text = TextEditingController(text: widget.draft)
    ..addListener(() => widget.onDraftChanged(_text.text));
  final _feed = ScrollController();

  bool _creating = false;
  bool _updating = false;
  bool _marking = false;
  bool _deleting = false;
  String? _removing;
  Object? _error;

  RequestsKey get _key => requestsKey(widget.companyId, widget.scope);

  @override
  void dispose() {
    _text.dispose();
    _feed.dispose();
    super.dispose();
  }

  /// Runs one change, then waits for the fresh list, so a card never shows its old state after the button.
  Future<bool> _change(Future<void> Function() call, void Function(bool busy) busy, {bool calendar = false}) async {
    setState(() {
      busy(true);
      _error = null;
    });
    try {
      await call();
      if (!mounted) return true;
      refreshAfterRequest(ref, calendar: calendar);
      try {
        await ref.read(myRequestsProvider(_key).future);
      } catch (_) {
        // The list shows its own error.
      }
      return true;
    } catch (error) {
      if (mounted) setState(() => _error = error);
      return false;
    } finally {
      if (mounted) setState(() => busy(false));
    }
  }

  void _toBottom() {
    if (_feed.hasClients) _feed.jumpTo(0);
  }

  Future<void> _send() async {
    final text = _text.text.trim();
    if (text.isEmpty || _creating) return;
    final scope = widget.scope;
    final sent = await _change(
      () => ref
          .read(apiProvider)
          .availability
          .createMyRequest(
            body: RequestIn(
              companyId: widget.companyId,
              periodId: scope.periodId,
              month: scope.periodId == null ? scope.month : null,
              text: text,
            ),
          ),
      (busy) => _creating = busy,
    );
    if (sent && mounted) {
      _text.clear();
      _toBottom();
    }
  }

  Future<void> _update(MyRequestOut request, RequestChangeIn change) => _change(
    () => ref.read(apiProvider).availability.updateMyRequest(requestId: request.id, body: change),
    (busy) => _updating = busy,
  );

  Future<void> _remove(MyRequestOut request) async {
    await _change(
      () => ref.read(apiProvider).availability.deleteMyRequest(requestId: request.id),
      (busy) => _deleting = busy,
    );
    if (mounted) setState(() => _removing = null);
  }

  /// "Zaznacz „nie mogę”": the same save as a tap in the calendar, so "Kiedy mogę" shows it too.
  Future<void> _markCannot(CannotMarkOut mark) => _change(
    () => ref
        .read(apiProvider)
        .availability
        .saveMyCalendar(
          body: CalendarIn(companyId: widget.companyId, days: markedDays(mark)),
        ),
    (busy) => _marking = busy,
    calendar: true,
  );

  @override
  Widget build(BuildContext context) {
    final requests = ref.watch(myRequestsProvider(_key));
    final all = requests.value;
    final editable = widget.scope.editable;
    final assistantReads = widget.assistantReads;
    // Lasting requests from earlier months belong to those months' chats ("Twoje prośby" lists them here too).
    final list = (all ?? const <MyRequestOut>[]).where((request) => !isCarried(request)).toList();
    // A question the assistant still remembers waits for an answer: the next message may be it.
    final asking = list.any((request) => request.canAnswer);

    final Widget feed;
    if (all == null) {
      feed = Padding(
        padding: const EdgeInsets.all(gutter),
        child: requests.hasError
            ? ErrorView(
                errorMessage(requests.error, 'Nie udało się wczytać rozmowy. Sprawdź internet i spróbuj jeszcze raz.'),
                onRetry: () => ref.invalidate(myRequestsProvider(_key)),
              )
            : const LoadingView('Wczytuję rozmowę…'),
      );
    } else if (list.isEmpty) {
      feed = ListView(
        padding: const EdgeInsets.all(gutter),
        children: [
          Semantics(
            header: true,
            child: Text(
              assistantReads ? 'W czym pomóc?' : 'Co warto uwzględnić w Twoim grafiku?',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            assistantReads
                ? 'Zapytaj, na przykład: „Kiedy mam następną zmianę?”. Albo napisz prośbę: „W piątki wolę pracować '
                      'rano”. Prośby zapiszę w „Twoich prośbach”.'
                : 'Na przykład: „W piątki wolę pracować rano”. Prośba trafi do „Twoich próśb” i do kierownika.',
            style: _muted,
          ),
        ],
      );
    } else {
      // Upside down, so the chat opens at the newest message and stays there while answers grow.
      feed = Semantics(
        label: 'Twoje prośby o grafiku',
        container: true,
        child: ListView.separated(
          controller: _feed,
          reverse: true,
          padding: const EdgeInsets.all(gutter),
          itemCount: list.length,
          separatorBuilder: (context, _) => const SizedBox(height: 24),
          itemBuilder: (context, index) {
            final request = list[list.length - 1 - index];
            return _Exchange(
              key: ValueKey(request.id),
              request: request,
              assistantReads: assistantReads,
              status: RequestStatus(
                request: request,
                editable: editable && request.status != MyRequestOutStatus.superseded,
                waiting: editable && request.canAnswer,
                busy: _updating,
                marking: _marking,
                only: widget.only,
                actions: RequestActions(
                  rewrite: (text) => _update(request, RequestChangeIn(text: text)),
                  toManager: () => _update(request, const RequestChangeIn(understood: false)),
                  markCannot: _markCannot,
                  setLasting: (lasting) => _update(request, RequestChangeIn(lasting: lasting)),
                ),
              ),
              remove: editable && !isSaved(request)
                  ? RemoveControl(
                      asking: _removing == request.id,
                      busy: _deleting,
                      onAsk: () => setState(() => _removing = request.id),
                      onCancel: () => setState(() => _removing = null),
                      onRemove: () => _remove(request),
                    )
                  : null,
            );
          },
        ),
      );
    }

    return Column(
      children: [
        Expanded(child: feed),
        DecoratedBox(
          decoration: const BoxDecoration(
            color: AppColors.surface,
            border: Border(top: BorderSide(color: AppColors.grid)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(gutter, 12, gutter, 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (_error != null) ...[InlineError(errorMessage(_error, networkProblem)), const SizedBox(height: 8)],
                  if (editable)
                    ChatComposer(
                      controller: _text,
                      onSend: _send,
                      label: assistantReads ? 'Twoja wiadomość' : 'Twoja prośba',
                      sendLabel: assistantReads ? 'Wyślij' : 'Wyślij prośbę',
                      placeholder: asking
                          ? 'Odpowiedz asystentowi…'
                          : assistantReads
                          ? 'Zapytaj albo opisz prośbę…'
                          : 'Opisz swoją prośbę…',
                      disabled: all == null,
                      sending: _creating,
                      footer: assistantReads ? null : 'Wiadomość dla kierownika.',
                    )
                  else
                    const Text(
                      'Prośby na ten okres są już zamknięte. Jeśli coś się zmieniło, porozmawiaj z kierownikiem.',
                      style: _muted,
                    ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// One message with what became of it: my words, a line saying where they went, and the assistant's answer.
class _Exchange extends StatelessWidget {
  const _Exchange({
    super.key,
    required this.request,
    required this.assistantReads,
    required this.status,
    required this.remove,
  });

  final MyRequestOut request;
  final bool assistantReads;
  final Widget status;
  final Widget? remove;

  @override
  Widget build(BuildContext context) {
    final request = this.request;
    final state = request.status;
    final where = state == MyRequestOutStatus.answered && request.question != null
        ? 'Asystent dopytuje'
        : state == MyRequestOutStatus.answered
        ? 'Odpowiedź asystenta'
        : state == MyRequestOutStatus.superseded
        ? 'Historia prośby'
        : state == MyRequestOutStatus.rejected
        ? 'Odrzucona'
        : state == MyRequestOutStatus.new2 && assistantReads
        ? 'Wysłane'
        : 'Zapisane w Twoich prośbach';
    final answer = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        status,
        HoursProposals(request: request),
      ],
    );
    final fromAssistant =
        state == MyRequestOutStatus.interpreted ||
        state == MyRequestOutStatus.answered ||
        (state == MyRequestOutStatus.new2 && assistantReads);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ChatMessage(mine: true, at: request.createdAt, child: Text(request.text)),
        Align(
          alignment: Alignment.centerRight,
          child: Wrap(
            alignment: WrapAlignment.end,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 4,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text(where, style: const TextStyle(fontSize: 12, color: AppColors.inkMuted)),
              ),
              ?remove,
            ],
          ),
        ),
        const SizedBox(height: 4),
        if (fromAssistant)
          ChatMessage(mine: false, child: answer)
        else
          Container(
            padding: const EdgeInsets.only(left: 12),
            decoration: const BoxDecoration(
              border: Border(left: BorderSide(color: AppColors.line, width: 2)),
            ),
            child: answer,
          ),
      ],
    );
  }
}
