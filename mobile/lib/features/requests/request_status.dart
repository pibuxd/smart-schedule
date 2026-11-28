import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../shared/dates.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../schedule/hours.dart';
import 'chat_parts.dart';
import 'request_words.dart';
import 'requests_data.dart';

const _small = TextStyle(fontSize: 14, color: AppColors.inkMuted);

/// What can be done about one message in the chat; each gives a future the card waits for.
class RequestActions {
  const RequestActions({
    required this.rewrite,
    required this.toManager,
    required this.markCannot,
    required this.setLasting,
  });

  final Future<void> Function(String text) rewrite;
  final Future<void> Function() toManager;
  final Future<void> Function(CannotMarkOut mark) markCannot;
  final Future<void> Function(bool lasting) setLasting;
}

/// How the message was understood, in plain words, with a way to say "that is not what I meant" (the website's
/// `RequestStatus`).
class RequestStatus extends StatelessWidget {
  const RequestStatus({
    super.key,
    required this.request,
    required this.editable,
    required this.waiting,
    required this.busy,
    required this.marking,
    required this.only,
    required this.actions,
  });

  final MyRequestOut request;
  final bool editable;

  /// The newest message of the chat: an open question waits for the next one.
  final bool waiting;
  final bool busy;
  final bool marking;

  /// "w grudniu": the month (or days of the period) of this chat, for "Tylko w grudniu".
  final String only;
  final RequestActions actions;

  @override
  Widget build(BuildContext context) {
    final request = this.request;
    final status = request.status;
    final reply = request.reply == null || request.reply!.isEmpty ? null : Text(request.reply!);
    Widget column(List<Widget> children) => Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final (i, child) in children.indexed) ...[if (i > 0) const SizedBox(height: 8), child],
      ],
    );
    Widget quiet(String label, VoidCallback? onPressed) => Align(
      alignment: Alignment.centerLeft,
      child: TextButton(onPressed: onPressed, child: Text(label)),
    );

    if (status == MyRequestOutStatus.rejected) {
      return column([
        Text(request.summary ?? 'Ta prośba została odrzucona.', style: _small),
        if (editable) quiet('Przekaż kierownikowi', busy ? null : actions.toManager),
      ]);
    }
    if (status == MyRequestOutStatus.superseded) {
      return const Text('Ta prośba została zastąpiona nowszą. Nie wpływa już na układanie grafiku.', style: _small);
    }
    if (status == MyRequestOutStatus.answered &&
        (request.reply != null || request.summary != null || request.question != null)) {
      return column([
        if (reply != null) reply else if (request.summary != null) Text(request.summary!),
        if (request.question != null) _Question(question: request.question!, waiting: waiting),
        if (editable) quiet('Niech przeczyta kierownik', busy ? null : actions.toManager),
      ]);
    }
    if (status == MyRequestOutStatus.interpreted && request.summary != null) {
      final marks = request.cannotMarks ?? const [];
      // In a request that may last, the wishes that count only here ("we wtorki nie mogę od 9 do 11").
      final periodOnly = (request.parts ?? const []).where((part) => !part.canLast).toList();
      return column([
        ?reply,
        Text.rich(
          TextSpan(
            children: [
              const TextSpan(
                text: 'Tak to zrozumieliśmy: ',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
              TextSpan(text: request.summary),
            ],
          ),
        ),
        Text(generatorWords(request, marked: marks.isNotEmpty), style: _small),
        if (editable && request.canLast)
          LastingChoice(lasting: request.lasting, only: only, disabled: busy, onChanged: actions.setLasting),
        if (editable && request.canLast && periodOnly.isNotEmpty)
          Text('Tylko $only: ${periodOnly.map((part) => clause(part.summary)).join('; ')}.', style: _small),
        if (request.notes.isNotEmpty) _Notes(notes: request.notes),
        if (editable)
          for (final mark in marks)
            CannotMarkCard(mark: mark, disabled: busy, marking: marking, onMark: () => actions.markCannot(mark)),
        if (editable) _WrongChoice(request: request, busy: busy, actions: actions),
      ]);
    }
    if (status == MyRequestOutStatus.new2) return const ChatTyping();
    return column([
      ?reply,
      const Text('Kierownik przeczyta tę prośbę sam. Generator nie użyje jej automatycznie.', style: _small),
    ]);
  }
}

/// The assistant's question back: it was not sure what the person meant and saves nothing until they answer.
class _Question extends StatelessWidget {
  const _Question({required this.question, required this.waiting});

  final String question;
  final bool waiting;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(question, style: const TextStyle(fontWeight: FontWeight.w600)),
        if (waiting) const Text('Odpowiedz niżej. Do tego czasu niczego nie zapisuję.', style: _small),
      ],
    );
  }
}

/// Notes from the app: the calendar says the opposite, or the shift is not on the person's position.
class _Notes extends StatelessWidget {
  const _Notes({required this.notes});

  final List<String> notes;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: AppColors.preferNotSoft, borderRadius: BorderRadius.circular(AppRadius.md)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final note in notes) Text(note, style: const TextStyle(fontSize: 14, color: AppColors.preferNot)),
        ],
      ),
    );
  }
}

/// "Tylko w grudniu" / "Na stałe": how long a saved request counts. "Na stałe" carries it over to every later month
/// until the person (or the manager) ends it there.
class LastingChoice extends StatelessWidget {
  const LastingChoice({
    super.key,
    required this.lasting,
    required this.only,
    required this.disabled,
    required this.onChanged,
  });

  final bool lasting;
  final String only;
  final bool disabled;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    Widget option(bool value, String label) {
      final chosen = lasting == value;
      return Semantics(
        selected: chosen,
        button: true,
        child: OutlinedButton(
          style: OutlinedButton.styleFrom(
            backgroundColor: chosen ? AppColors.accent : AppColors.surface,
            foregroundColor: chosen ? AppColors.accentInk : AppColors.ink,
            side: BorderSide(color: chosen ? AppColors.accent : AppColors.line, width: 2),
            minimumSize: const Size(0, touch),
            padding: const EdgeInsets.symmetric(horizontal: 12),
            textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
          ),
          onPressed: disabled ? null : () => chosen ? null : onChanged(value),
          child: Text(label),
        ),
      );
    }

    return Semantics(
      label: 'Jak długo obowiązuje prośba',
      container: true,
      child: Wrap(spacing: 4, runSpacing: 4, children: [option(false, 'Tylko $only'), option(true, 'Na stałe')]),
    );
  }
}

/// Days the request says the person cannot work that the calendar does not show so (in the chat, and under a lasting
/// request from an earlier month in "Twoje prośby", for this month's days). "Nie mogę" is always a whole day
/// (Piotr, 25.11.2026), so with hours the button marks those days "mogę" only in the rest of the day.
class CannotMarkCard extends StatelessWidget {
  const CannotMarkCard({
    super.key,
    required this.mark,
    required this.disabled,
    required this.marking,
    required this.onMark,
  });

  final CannotMarkOut mark;
  final bool disabled;
  final bool marking;
  final VoidCallback onMark;

  @override
  Widget build(BuildContext context) {
    final hours = markHours(mark);
    final rest = windowsWords(mark.windows ?? const []);
    final own = windowsWords(mark.own ?? const []);
    final dropped = windowsWords(mark.dropped ?? const []);
    final days = mark.days.map(shortDate).join(', ');
    final text = mark.wholeDay
        ? 'W kalendarzu te dni mają „Nie mogę” przez cały dzień, a prośba mówi tylko o godzinach $hours: $days.'
        : own.isNotEmpty
        ? 'W kalendarzu masz w te dni godziny $own, a prośba mówi, że nie możesz $hours: $days.'
        : rest.isNotEmpty
        ? 'W kalendarzu te dni są nadal do pracy także w godzinach $hours: $days.'
        : 'W kalendarzu te dni są nadal do pracy: $days.';
    final label = rest.isNotEmpty ? 'Zaznacz „Mogę” $rest' : 'Zaznacz „nie mogę”';
    final muted = mark.wholeDay
        ? 'Nie dostaniesz wtedy zmiany, która zahacza o godziny $hours. Nie możesz przez cały dzień? Zostaw tak, jak '
              'jest.'
        : own.isNotEmpty && rest.isEmpty
        ? 'Tego jeszcze nie ma w kalendarzu. Poza tymi godzinami nie zostaje nic do pracy, więc przycisk zaznaczy „nie '
              'mogę” na cały dzień.'
        : hours.isNotEmpty
        ? 'Tego jeszcze nie ma w kalendarzu. Naciśnij przycisk, a nie dostaniesz zmiany, która zahacza o godziny '
              '$hours.'
        : '';
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(text, style: const TextStyle(fontSize: 14)),
          if (muted.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              '$muted${dropped.isEmpty ? '' : ' Kalendarz mieści dwa przedziały godzin dziennie, więc $dropped też '
                        'będzie bez pracy.'}',
              style: _small,
            ),
          ],
          const SizedBox(height: 8),
          // The hours make a long label: the whole width, and room for a second line.
          OutlinedButton(
            style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10)),
            onPressed: disabled || marking ? null : onMark,
            child: Text(marking ? 'Zapisuję…' : label, textAlign: TextAlign.center),
          ),
        ],
      ),
    );
  }
}

/// "Nie o to mi chodziło": first a way to write the request again (the assistant reads it anew), and only as a second
/// choice handing it to the manager as written.
class _WrongChoice extends StatefulWidget {
  const _WrongChoice({required this.request, required this.busy, required this.actions});

  final MyRequestOut request;
  final bool busy;
  final RequestActions actions;

  @override
  State<_WrongChoice> createState() => _WrongChoiceState();
}

class _WrongChoiceState extends State<_WrongChoice> {
  bool _open = false;
  late final _text = TextEditingController(text: widget.request.text);

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final busy = widget.busy;
    if (!_open) {
      return Align(
        alignment: Alignment.centerLeft,
        child: TextButton(
          onPressed: busy ? null : () => setState(() => _open = true),
          child: const Text('Nie o to mi chodziło'),
        ),
      );
    }
    return ListenableBuilder(
      listenable: _text,
      builder: (context, _) {
        final text = _text.text.trim();
        final changed = text.isNotEmpty && text != widget.request.text;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _text,
              minLines: 3,
              maxLines: 6,
              maxLength: 1000,
              decoration: const InputDecoration(labelText: 'Napisz to inaczej', counterText: ''),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                FilledButton(
                  onPressed: busy || !changed ? null : () => widget.actions.rewrite(text),
                  child: const Text('Wyślij poprawioną'),
                ),
                TextButton(
                  onPressed: busy ? null : widget.actions.toManager,
                  child: const Text('Niech przeczyta kierownik'),
                ),
                TextButton(onPressed: busy ? null : () => setState(() => _open = false), child: const Text('Anuluj')),
              ],
            ),
          ],
        );
      },
    );
  }
}

/// The bin, and a second tap to be sure.
class RemoveControl extends StatelessWidget {
  const RemoveControl({
    super.key,
    required this.asking,
    required this.busy,
    required this.onAsk,
    required this.onCancel,
    required this.onRemove,
  });

  final bool asking;
  final bool busy;
  final VoidCallback onAsk;
  final VoidCallback onCancel;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    if (!asking) {
      return IconButton(tooltip: 'Usuń prośbę', onPressed: onAsk, icon: const Icon(Icons.delete_outline, size: 20));
    }
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      alignment: WrapAlignment.end,
      children: [
        const Text('Usunąć tę prośbę?', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
        TextButton(onPressed: busy ? null : onRemove, child: const Text('Tak, usuń')),
        TextButton(onPressed: onCancel, child: const Text('Nie')),
      ],
    );
  }
}

/// Reports of other hours the assistant prepared from one message (overtime, leaving early). Nothing goes to the
/// manager by itself: "Wyślij kierownikowi" sends one, as the same report from "Mój grafik".
class HoursProposals extends StatelessWidget {
  const HoursProposals({super.key, required this.request, this.readOnly = false});

  final MyRequestOut request;

  /// The company's access has expired (the chat opened to read): nothing can be sent.
  final bool readOnly;

  @override
  Widget build(BuildContext context) {
    final proposals = request.hoursReports ?? const [];
    if (proposals.isEmpty) return const SizedBox.shrink();
    return Semantics(
      label: 'Zgłoszenia innych godzin',
      container: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final proposal in proposals)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: _Proposal(
                key: ValueKey('${proposal.date}:${proposal.startTime}:${proposal.endTime}'),
                proposal: proposal,
                requestId: request.id,
                readOnly: readOnly,
              ),
            ),
        ],
      ),
    );
  }
}

const _sentWords = {
  HoursProposalOutSentStatusValue.pending: 'Wysłane. Czeka na kierownika.',
  HoursProposalOutSentStatusValue.approved: 'Kierownik zatwierdził te godziny.',
  HoursProposalOutSentStatusValue.rejected: 'Kierownik odrzucił te godziny.',
  HoursProposalOutSentStatusValue.cancelled: 'Zgłoszenie wycofane.',
  HoursProposalOutSentStatusValue.replaced: 'Zastąpione innymi godzinami.',
  HoursProposalOutSentStatusValue.expired: 'Nie masz już tej zmiany w grafiku, więc te godziny się nie liczą.',
};

class _Proposal extends ConsumerStatefulWidget {
  const _Proposal({super.key, required this.proposal, required this.requestId, required this.readOnly});

  final HoursProposalOut proposal;
  final String requestId;
  final bool readOnly;

  @override
  ConsumerState<_Proposal> createState() => _ProposalState();
}

class _ProposalState extends ConsumerState<_Proposal> {
  bool _sending = false;
  Object? _error;

  Future<void> _send(String assignmentId) async {
    final proposal = widget.proposal;
    final container = ProviderScope.containerOf(context, listen: false);
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await ref
          .read(apiProvider)
          .worktime
          .reportMyHours(
            body: ReportHoursIn(
              assignmentId: assignmentId,
              startTime: proposal.startTime,
              endTime: proposal.endTime,
              reason: proposal.reason,
              requestId: widget.requestId,
            ),
          );
      refreshAfterRequest(container, schedule: true);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final proposal = widget.proposal;
    final status = switch (proposal.sentStatus) {
      HoursProposalOutSentStatusKnown(:final value) => value,
      _ => null,
    };
    final assignmentId = proposal.assignmentId;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Row(
            children: [
              Icon(Icons.schedule, size: 16, color: AppColors.inkMuted),
              SizedBox(width: 6),
              Flexible(
                child: Text(
                  'Inne godziny zmiany',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.inkMuted),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text:
                      '${dayTitle(parseDate(proposal.date))}: ${shortTime(proposal.startTime)}–'
                      '${shortTime(proposal.endTime)}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                TextSpan(
                  text:
                      ' zamiast ${shortTime(proposal.plannedStartTime)}–${shortTime(proposal.plannedEndTime)} '
                      '(${differenceText(proposal.differenceMinutes)})',
                ),
              ],
            ),
          ),
          Text(
            '${proposal.positionName}, ${proposal.locationName}'
            '${proposal.reason.isEmpty ? '' : '. Powód: ${proposal.reason}'}',
            style: _small,
          ),
          const SizedBox(height: 8),
          if (proposal.sentStatus != null)
            Semantics(
              liveRegion: true,
              child: Text(
                status == null ? 'Wysłane.' : _sentWords[status]!,
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: status == HoursProposalOutSentStatusValue.approved ? AppColors.prefer : AppColors.inkMuted,
                ),
              ),
            )
          else if (assignmentId == null)
            const Text('Grafik się zmienił i nie masz już tej zmiany, więc tego zgłoszenia nie wyślesz.', style: _small)
          else if (widget.readOnly)
            const Text(
              'Firma ma teraz wstrzymany dostęp do aplikacji, więc tego zgłoszenia nie wyślesz.',
              style: _small,
            )
          else
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton(
                onPressed: _sending ? null : () => _send(assignmentId),
                child: Text(_sending ? 'Wysyłam…' : 'Wyślij kierownikowi'),
              ),
            ),
          if (_error != null) ...[const SizedBox(height: 8), InlineError(errorMessage(_error, networkProblem))],
        ],
      ),
    );
  }
}
