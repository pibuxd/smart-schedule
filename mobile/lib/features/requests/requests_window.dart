import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../shared/dates.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'chat_parts.dart';
import 'employee_chat.dart';
import 'request_status.dart';
import 'requests_data.dart';
import 'request_words.dart';

const _muted = TextStyle(fontSize: 14, color: AppColors.inkMuted);

/// "Twoje prośby" under the calendar (the website's `RequestsWindow`): only the requests that count (understood by the
/// assistant, or left for the manager to read); each can be corrected or removed here. The conversation itself is in
/// the chat; while this window is on screen, the "Asystent" tab opens it on this window's month too. Lasting requests
/// from earlier months are listed as well ("Na stałe od grudnia"), with "Zakończ" instead of editing.
class RequestsWindow extends ConsumerStatefulWidget {
  const RequestsWindow({
    super.key,
    required this.companyId,
    required this.scope,
    required this.start,
    required this.end,
    required this.assistantReads,
  });

  final String companyId;
  final ChatScope scope;

  /// The first and last day of the period (month) on screen.
  final String start;
  final String end;
  final bool assistantReads;

  @override
  ConsumerState<RequestsWindow> createState() => _RequestsWindowState();
}

class _RequestsWindowState extends ConsumerState<RequestsWindow> {
  late final EmployeeChatMemory _memory = ref.read(employeeChatMemoryProvider);

  ({String id, TextEditingController text})? _editing;
  String? _removing;
  String? _ending;
  bool _updating = false;
  bool _deleting = false;
  bool _finishing = false;
  bool _marking = false;
  Object? _error;

  RequestsKey get _key => requestsKey(widget.companyId, widget.scope);

  @override
  void initState() {
    super.initState();
    _memory.screen = widget.scope;
  }

  // By identity: a fresh calendar builds a new window before the old one goes, and the old one must not clear it.
  @override
  void didUpdateWidget(RequestsWindow old) {
    super.didUpdateWidget(old);
    if (identical(_memory.screen, old.scope)) _memory.screen = widget.scope;
  }

  @override
  void dispose() {
    if (identical(_memory.screen, widget.scope)) _memory.screen = null;
    _editing?.text.dispose();
    super.dispose();
  }

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
        // The window shows its own error.
      }
      return true;
    } catch (error) {
      if (mounted) setState(() => _error = error);
      return false;
    } finally {
      if (mounted) setState(() => busy(false));
    }
  }

  Future<bool> _update(MyRequestOut request, RequestChangeIn change) => _change(
    () => ref.read(apiProvider).availability.updateMyRequest(requestId: request.id, body: change),
    (busy) => _updating = busy,
  );

  void _edit(MyRequestOut request) {
    _editing?.text.dispose();
    setState(() => _editing = (id: request.id, text: TextEditingController(text: request.text)));
  }

  void _stopEditing() {
    _editing?.text.dispose();
    setState(() => _editing = null);
  }

  Future<void> _save(MyRequestOut request) async {
    final text = _editing?.text.text.trim() ?? '';
    if (await _update(request, RequestChangeIn(text: text)) && mounted && _editing?.id == request.id) _stopEditing();
  }

  Future<void> _remove(MyRequestOut request) async {
    await _change(
      () => ref.read(apiProvider).availability.deleteMyRequest(requestId: request.id),
      (busy) => _deleting = busy,
    );
    if (mounted) setState(() => _removing = null);
  }

  Future<void> _end(MyRequestOut request, bool ended) async {
    final scope = widget.scope;
    await _change(
      () => ref
          .read(apiProvider)
          .availability
          .endMyRequest(
            requestId: request.id,
            body: RequestEndIn(
              companyId: widget.companyId,
              periodId: scope.periodId,
              month: scope.periodId == null ? scope.month : null,
              ended: ended,
            ),
          ),
      (busy) => _finishing = busy,
    );
    if (mounted) setState(() => _ending = null);
  }

  /// A lasting "nie mogę" written in an earlier month offers this month's days too: the same save as a tap in the
  /// calendar (27.11.2026).
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

  void _openChat() => openEmployeeChat(context, ref, scope: widget.scope);

  @override
  Widget build(BuildContext context) {
    final requests = ref.watch(myRequestsProvider(_key));
    final list = requests.value ?? const <MyRequestOut>[];
    final editable = widget.scope.editable;
    final assistantReads = widget.assistantReads;
    final own = list.where((request) => !isCarried(request)).toList();
    final saved = own.where(isSaved).toList();
    final carried = list.where(isCarried).toList();
    final only = periodWords(widget.start, widget.end);
    final since = sinceWords(widget.start);
    // Messages the assistant asked about and nobody answered: listed apart, so a request is never lost quietly.
    final waiting = editable ? own.where((request) => request.waiting).toList() : const <MyRequestOut>[];
    final reading = assistantReads && own.any((request) => request.status == MyRequestOutStatus.new2);
    // The newest message left a trace only in the chat: say so here, so it does not look lost.
    final last = own.isEmpty ? null : own.last;
    final notSaved =
        last != null &&
            !waiting.contains(last) &&
            (last.status == MyRequestOutStatus.rejected || last.status == MyRequestOutStatus.answered)
        ? last
        : null;

    Widget editForm(MyRequestOut request) => _EditForm(
      request: request,
      controller: _editing!.text,
      busy: _updating,
      assistantReads: assistantReads,
      onCancel: _stopEditing,
      onSave: () => _save(request),
    );

    const gap = SizedBox(height: 12);
    return Container(
      padding: const EdgeInsets.all(gutter),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            runSpacing: 8,
            children: [
              Semantics(header: true, child: Text('Twoje prośby', style: Theme.of(context).textTheme.titleMedium)),
              if (editable || list.isNotEmpty)
                OutlinedButton.icon(
                  onPressed: _openChat,
                  icon: const Icon(Icons.chat_bubble_outline, size: 18),
                  label: Text(
                    !editable
                        ? 'Pokaż rozmowę'
                        : assistantReads
                        ? 'Napisz do asystenta'
                        : 'Napisz prośbę',
                  ),
                ),
            ],
          ),
          if (requests.isLoading && !requests.hasValue) ...[
            gap,
            Semantics(liveRegion: true, child: const Text('Wczytuję prośby…', style: _muted)),
          ],
          if (requests.hasError && !requests.hasValue) ...[
            gap,
            const InlineError('Nie udało się wczytać Twoich próśb.'),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () => ref.invalidate(myRequestsProvider(_key)),
                child: const Text('Spróbuj ponownie'),
              ),
            ),
          ],
          if (waiting.isNotEmpty)
            Semantics(
              label: 'Czekają na Twoją odpowiedź',
              container: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final request in waiting) ...[
                    gap,
                    _Row(
                      dashed: true,
                      child: _editing?.id == request.id
                          ? editForm(request)
                          : Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                // A second or third question: the earlier messages of the same request come first.
                                for (final earlier in request.exchange ?? const <AskedOut>[])
                                  Padding(
                                    padding: const EdgeInsets.only(bottom: 8),
                                    child: Text(earlier.text, style: _muted),
                                  ),
                                Text(request.text),
                                const SizedBox(height: 8),
                                Text('Nie jest zapisana. Asystent pyta: ${request.question ?? ''}', style: _muted),
                                const SizedBox(height: 8),
                                Wrap(
                                  spacing: 8,
                                  runSpacing: 4,
                                  children: [
                                    OutlinedButton(
                                      onPressed: request.canAnswer ? _openChat : () => _edit(request),
                                      child: Text(request.canAnswer ? 'Odpowiedz' : 'Napisz ją od nowa'),
                                    ),
                                    TextButton(
                                      onPressed: _updating
                                          ? null
                                          : () => _update(request, const RequestChangeIn(understood: false)),
                                      child: const Text('Niech przeczyta kierownik'),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                    ),
                  ],
                ],
              ),
            ),
          if (requests.hasValue && saved.isEmpty && carried.isEmpty && waiting.isEmpty) ...[
            gap,
            Text(
              editable
                  ? 'Nie masz jeszcze próśb. Napisz, czego kalendarz nie powie, na przykład: „W piątki wolę pracować '
                        'rano”.'
                  : 'Nie masz próśb na ten okres.',
              style: _muted,
            ),
          ],
          if (saved.isNotEmpty)
            Semantics(
              label: 'Zapisane prośby',
              container: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final request in saved) ...[
                    gap,
                    _Row(
                      child: editable && _editing?.id == request.id
                          ? editForm(request)
                          : _Saved(
                              request: request,
                              editable: editable,
                              only: only,
                              busy: _updating,
                              onLasting: (lasting) => _update(request, RequestChangeIn(lasting: lasting)),
                              // The question and its two answers need the whole width of a phone.
                              side: editable && _removing != request.id
                                  ? Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        IconButton(
                                          tooltip: 'Edytuj prośbę',
                                          onPressed: () => _edit(request),
                                          icon: const Icon(Icons.edit_outlined, size: 20),
                                        ),
                                        RemoveControl(
                                          asking: false,
                                          busy: _deleting,
                                          onAsk: () => setState(() => _removing = request.id),
                                          onCancel: () => setState(() => _removing = null),
                                          onRemove: () => _remove(request),
                                        ),
                                      ],
                                    )
                                  : null,
                              below: editable && _removing == request.id
                                  ? Align(
                                      alignment: Alignment.centerRight,
                                      child: RemoveControl(
                                        asking: true,
                                        busy: _deleting,
                                        onAsk: () {},
                                        onCancel: () => setState(() => _removing = null),
                                        onRemove: () => _remove(request),
                                      ),
                                    )
                                  : null,
                            ),
                    ),
                  ],
                ],
              ),
            ),
          if (carried.isNotEmpty)
            Semantics(
              label: 'Prośby na stałe z wcześniejszych miesięcy',
              container: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final request in carried) ...[
                    gap,
                    _Row(
                      dashed: request.ended,
                      child: _Carried(
                        request: request,
                        since: since,
                        marks: editable && !request.ended
                            ? [
                                for (final mark in request.cannotMarks ?? const <CannotMarkOut>[])
                                  CannotMarkCard(
                                    mark: mark,
                                    disabled: _finishing,
                                    marking: _marking,
                                    onMark: () => _markCannot(mark),
                                  ),
                              ]
                            : const [],
                        action: !editable
                            ? null
                            : !request.ended
                            ? _EndControl(
                                since: since,
                                asking: _ending == request.id,
                                busy: _finishing,
                                onAsk: () => setState(() => _ending = request.id),
                                onCancel: () => setState(() => _ending = null),
                                onEnd: () => _end(request, true),
                              )
                            : request.endedBy == MyRequestOutEndedBy.employee
                            ? TextButton(
                                onPressed: _finishing ? null : () => _end(request, false),
                                child: const Text('Przywróć'),
                              )
                            : null,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          if (reading) ...[gap, const ChatTyping(text: 'Asystent myśli…')],
          if (notSaved != null) ...[
            gap,
            Text(
              notSaved.status == MyRequestOutStatus.rejected
                  ? 'Twoja ostatnia wiadomość została odrzucona i nie jest prośbą.'
                  : 'Asystent odpowiedział na Twoją ostatnią wiadomość.',
              style: _muted,
            ),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(onPressed: _openChat, child: const Text('Pokaż odpowiedź')),
            ),
          ],
          if (_error != null) ...[gap, InlineError(errorMessage(_error, networkProblem))],
        ],
      ),
    );
  }
}

/// One request in the window: a box with a solid edge, or a dashed one for what does not count (yet).
class _Row extends StatelessWidget {
  const _Row({required this.child, this.dashed = false});

  final Widget child;
  final bool dashed;

  @override
  Widget build(BuildContext context) {
    final box = Padding(padding: const EdgeInsets.fromLTRB(12, 10, 4, 10), child: child);
    if (dashed) return CustomPaint(painter: const _DashedEdge(), child: box);
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: AppColors.grid, width: 1.5),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: box,
    );
  }
}

class _DashedEdge extends CustomPainter {
  const _DashedEdge();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.line
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    final edge = Path()
      ..addRRect(RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(AppRadius.md)).deflate(0.75));
    for (final metric in edge.computeMetrics()) {
      for (var at = 0.0; at < metric.length; at += 9) {
        canvas.drawPath(metric.extractPath(at, at + 5), paint);
      }
    }
  }

  @override
  bool shouldRepaint(_DashedEdge old) => false;
}

/// A saved request: its words, how it was understood, how long it counts, and (while editable) edit and remove.
class _Saved extends StatelessWidget {
  const _Saved({
    required this.request,
    required this.editable,
    required this.only,
    required this.busy,
    required this.onLasting,
    required this.side,
    required this.below,
  });

  final MyRequestOut request;
  final bool editable;
  final String only;
  final bool busy;
  final ValueChanged<bool> onLasting;

  /// Edit and remove, beside the words; [below] takes the whole width (the question before removing).
  final Widget? side;
  final Widget? below;

  @override
  Widget build(BuildContext context) {
    final request = this.request;
    final understood = request.status == MyRequestOutStatus.interpreted;
    final summary = request.summary;
    final note =
        '${understood && summary != null
            ? 'Asystent zrozumiał: $summary'
            : understood
            ? 'Zostanie uwzględniona przy układaniu grafiku.'
            : 'Kierownik przeczyta ją sam.'}'
        '${!editable && request.lasting ? ' Na stałe.' : ''}'
        '${request.endsFrom == null ? '' : ' Nie obowiązuje ${sinceWords(request.endsFrom!)}.'}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(request.text),
                    Text(note, style: _muted),
                  ],
                ),
              ),
            ),
            ?side,
          ],
        ),
        if (editable && request.canLast) ...[
          const SizedBox(height: 8),
          LastingChoice(lasting: request.lasting, only: only, disabled: busy, onChanged: onLasting),
        ],
        ?below,
      ],
    );
  }
}

/// A lasting request from an earlier month: it counts here until ended ("Zakończ"), and an end can be taken back.
class _Carried extends StatelessWidget {
  const _Carried({required this.request, required this.since, required this.marks, required this.action});

  final MyRequestOut request;
  final String since;
  final List<Widget> marks;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final request = this.request;
    final note = request.ended
        ? 'Zakończona: nie obowiązuje $since.'
              '${request.endedBy == MyRequestOutEndedBy.manager ? ' Zakończył ją kierownik.' : ''}'
        : 'Na stałe ${sinceWords(request.carriedFrom!)}.'
              '${request.summary != null ? ' Asystent zrozumiał: ${request.summary}' : ' Kierownik przeczyta ją sam.'}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(request.text, style: request.ended ? const TextStyle(color: AppColors.inkMuted) : null),
        Text(note, style: _muted),
        if (action != null) Align(alignment: Alignment.centerLeft, child: action),
        for (final mark in marks) ...[const SizedBox(height: 8), mark],
      ],
    );
  }
}

/// "Zakończ" for a lasting request from an earlier month, and a second tap to be sure.
class _EndControl extends StatelessWidget {
  const _EndControl({
    required this.since,
    required this.asking,
    required this.busy,
    required this.onAsk,
    required this.onCancel,
    required this.onEnd,
  });

  /// "od stycznia": the month on screen, from which it stops counting.
  final String since;
  final bool asking;
  final bool busy;
  final VoidCallback onAsk;
  final VoidCallback onCancel;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context) {
    if (!asking) return TextButton(onPressed: onAsk, child: const Text('Zakończ'));
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text('Zakończyć $since?', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
        TextButton(onPressed: busy ? null : onEnd, child: const Text('Tak, zakończ')),
        TextButton(onPressed: onCancel, child: const Text('Nie')),
      ],
    );
  }
}

/// Writing a request again: the assistant reads the new text from the start.
class _EditForm extends StatelessWidget {
  const _EditForm({
    required this.request,
    required this.controller,
    required this.busy,
    required this.assistantReads,
    required this.onCancel,
    required this.onSave,
  });

  final MyRequestOut request;
  final TextEditingController controller;
  final bool busy;
  final bool assistantReads;
  final VoidCallback onCancel;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final text = controller.text.trim();
        return Padding(
          padding: const EdgeInsets.only(right: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: controller,
                minLines: 3,
                maxLines: 6,
                maxLength: 1000,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(labelText: 'Treść prośby', counterText: ''),
              ),
              const SizedBox(height: 8),
              Text(
                '${request.waiting ? 'Napisz całą prośbę razem z odpowiedzią na pytanie.' : 'Kierownik zobaczy '
                          'poprawioną treść. Jego wcześniejsza decyzja i nadana prośbie ważność pozostaną w mocy.'}'
                '${assistantReads ? ' Po zmianie tekstu zewnętrzny asystent AI przeczyta prośbę ponownie.' : ''}',
                style: _muted,
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  FilledButton(
                    onPressed: busy || text.isEmpty || text == request.text ? null : onSave,
                    child: const Text('Zapisz prośbę'),
                  ),
                  TextButton(onPressed: busy ? null : onCancel, child: const Text('Anuluj')),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}
