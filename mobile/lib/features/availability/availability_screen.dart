import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../shared/dates.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../employee/employee_shell.dart';
import '../schedule/schedule_data.dart';
import 'availability_calendar.dart';
import 'availability_data.dart';
import 'day_hours_sheet.dart';
import 'marks.dart';
import 'state_look.dart';

const _title = 'Kiedy mogę pracować';
const _loadFailed = 'Nie udało się wczytać kalendarza. Sprawdź internet i spróbuj jeszcze raz.';

/// How many months ahead of the current one the calendar reaches.
const _monthsAhead = 3;

/// How far a notification may open the calendar (the server takes marks up to a year ahead).
const _linkMonthsAhead = 12;

/// "Kiedy mogę", the website's `AvailabilityScreen`: always open, the employee marks days month by month, also before
/// the manager asks. When the manager has asked for a period, the screen opens on it and shows the deadline and
/// "Wyślij kierownikowi". [month] ("2026-12", from a notification) opens that month instead.
class AvailabilityTab extends ConsumerStatefulWidget {
  const AvailabilityTab({super.key, this.month});

  final String? month;

  @override
  ConsumerState<AvailabilityTab> createState() => _AvailabilityTabState();
}

class _AvailabilityTabState extends ConsumerState<AvailabilityTab> {
  String? _chosen;

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final company = session is SessionReady ? session.company : null;
    if (company == null) return const TabScreen(title: _title, children: []);
    final today = ref.read(clockProvider)();
    final thisMonth = monthOf(toIsoDate(today));
    final wanted = widget.month;
    // A notification about a later period (March while December is still open) links past the usual reach: the
    // month opens when the employee has an open period there, else the screen falls back as usual.
    final far =
        wanted != null &&
            wanted.compareTo(addMonths(thisMonth, _monthsAhead)) > 0 &&
            wanted.compareTo(addMonths(thisMonth, _linkMonthsAhead)) <= 0
        ? wanted
        : null;
    final availability = ref.watch(myAvailabilityProvider(company.id));
    final farCalendar = far == null ? null : ref.watch(myCalendarProvider((companyId: company.id, month: far)));

    final data = availability.value;
    if (data == null || (farCalendar != null && farCalendar.isLoading && !farCalendar.hasValue)) {
      return TabScreen(
        title: _title,
        children: [
          if (availability.hasError)
            ErrorView(
              errorMessage(availability.error, _loadFailed),
              onRetry: () => ref.invalidate(myAvailabilityProvider(company.id)),
            )
          else
            const LoadingView('Wczytuję kalendarz…'),
        ],
      );
    }
    final period = data.period;
    final farPeriod = farCalendar?.value?.period;
    final todayIso = toIsoDate(today);
    final requested = period == null ? null : monthOf(period.start.compareTo(todayIso) < 0 ? todayIso : period.start);
    final lastMonth = ([
      addMonths(thisMonth, _monthsAhead),
      period == null ? thisMonth : monthOf(period.end),
      farPeriod == null ? thisMonth : monthOf(farPeriod.end),
    ]..sort()).last;
    final linked = wanted != null && wanted.compareTo(thisMonth) >= 0 && wanted.compareTo(lastMonth) <= 0
        ? wanted
        : null;
    final month = _chosen ?? linked ?? requested ?? thisMonth;

    return _MonthEditor(
      key: ValueKey('${company.id}:$month'),
      companyId: company.id,
      month: month,
      readOnly: company.readOnly,
      today: today,
      pager: ({required bool busy}) => _MonthPager(
        month: month,
        onChange: (month) => setState(() => _chosen = month),
        canGoBack: !busy && month.compareTo(thisMonth) > 0,
        canGoForward: !busy && month.compareTo(lastMonth) < 0,
      ),
    );
  }
}

typedef _PagerBuilder = Widget Function({required bool busy});

class _MonthPager extends StatelessWidget {
  const _MonthPager({required this.month, required this.onChange, required this.canGoBack, required this.canGoForward});

  final String month;
  final ValueChanged<String> onChange;
  final bool canGoBack;
  final bool canGoForward;

  @override
  Widget build(BuildContext context) {
    Widget arrow(IconData icon, String label, bool enabled, int by) => IconButton.outlined(
      tooltip: label,
      onPressed: enabled ? () => onChange(addMonths(month, by)) : null,
      style: IconButton.styleFrom(
        foregroundColor: AppColors.accent,
        backgroundColor: AppColors.surface,
        side: const BorderSide(color: AppColors.line, width: 2),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadius.md)),
        minimumSize: const Size.square(touch),
      ),
      icon: Icon(icon, size: 26, semanticLabel: label),
    );
    return Row(
      children: [
        arrow(Icons.chevron_left, 'Poprzedni miesiąc', canGoBack, -1),
        Expanded(
          child: Semantics(
            header: true,
            liveRegion: true,
            child: Text(
              monthName(month),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
            ),
          ),
        ),
        arrow(Icons.chevron_right, 'Następny miesiąc', canGoForward, 1),
      ],
    );
  }
}

class _MonthEditor extends ConsumerWidget {
  const _MonthEditor({
    super.key,
    required this.companyId,
    required this.month,
    required this.readOnly,
    required this.today,
    required this.pager,
  });

  final String companyId;
  final String month;
  final bool readOnly;
  final DateTime today;
  final _PagerBuilder pager;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final key = (companyId: companyId, month: month);
    final calendar = ref.watch(myCalendarProvider(key));
    final initial = calendar.value;
    if (initial == null) {
      return TabScreen(
        title: _title,
        children: [
          pager(busy: false),
          const SizedBox(height: 16),
          if (calendar.hasError)
            ErrorView(errorMessage(calendar.error, _loadFailed), onRetry: () => ref.invalidate(myCalendarProvider(key)))
          else
            const LoadingView('Wczytuję kalendarz…'),
        ],
      );
    }
    // A fresh read (pull to refresh) starts the editor again from what the server has.
    return _Editor(
      key: ObjectKey(initial),
      companyId: companyId,
      month: month,
      readOnly: readOnly,
      today: today,
      initial: initial,
      pager: pager,
    );
  }
}

enum _SaveStatus { saved, saving, failed }

class _Editor extends ConsumerStatefulWidget {
  const _Editor({
    super.key,
    required this.companyId,
    required this.month,
    required this.readOnly,
    required this.today,
    required this.initial,
    required this.pager,
  });

  final String companyId;
  final String month;
  final bool readOnly;
  final DateTime today;
  final MyCalendarOut initial;
  final _PagerBuilder pager;

  @override
  ConsumerState<_Editor> createState() => _EditorState();
}

class _EditorState extends ConsumerState<_Editor> {
  late Marks _marks = marksFromServer(widget.initial.days);
  late DateTime? _submittedAt = widget.initial.submittedAt;
  late final Set<String> _locked = widget.initial.locked.toSet();
  // Days of a schedule the manager has arranged but not published yet: "Mój grafik" does not show them.
  late final Set<String> _unpublished = (widget.initial.unpublished ?? const []).toSet();
  late final List<String> _dates = [
    for (var day = parseDate(widget.initial.start); !day.isAfter(parseDate(widget.initial.end)); day = addDays(day, 1))
      toIsoDate(day),
  ];

  /// What a tap marks; [_hoursTool] = a tap opens the day's hours instead ("Godziny dnia").
  AvailabilityState _tool = AvailabilityState.cannot;
  bool _hoursTool = false;

  _SaveStatus _status = _SaveStatus.saved;
  String? _saveError;
  // Writes go one after another, so a later choice for a day never lands before an earlier one.
  Future<void> _queue = Future.value();
  int _pending = 0;
  final Marks _failed = {};

  bool _submitting = false;
  Object? _submitError;

  bool get _editable => !widget.readOnly && _locked.length < _dates.length;

  void _send(Marks changes) {
    if (changes.isEmpty) return;
    _pending += 1;
    setState(() => _status = _SaveStatus.saving);
    final api = ref.read(apiProvider);
    final body = CalendarIn(
      companyId: widget.companyId,
      days: [for (final entry in changes.entries) toDayIn(entry.key, entry.value)],
    );
    _queue = _queue.then((_) async {
      try {
        await api.availability.saveMyCalendar(body: body);
        for (final date in changes.keys) {
          _failed.remove(date);
        }
      } catch (error) {
        for (final date in changes.keys) {
          _failed[date] = markOf(_marks, date);
        }
        _saveError = errorMessage(error, networkProblem);
      } finally {
        _pending -= 1;
        if (_pending == 0 && mounted) {
          setState(() => _status = _failed.isEmpty ? _SaveStatus.saved : _SaveStatus.failed);
        }
      }
    });
  }

  void _apply(String date, Mark mark) {
    setState(() => _marks = {..._marks, date: mark});
    _send({date: mark});
  }

  void _tapDay(String date) {
    if (!_editable || _locked.contains(date)) return;
    final before = markOf(_marks, date);
    // A tap on a day that already shows the chosen state opens it: its hours can be seen and changed.
    if (_hoursTool || before.state == _tool) {
      _openDay(date);
      return;
    }
    _apply(date, Mark(_tool));
  }

  Future<void> _openDay(String date) async {
    final mark = await showDayHoursSheet(context, date: date, mark: markOf(_marks, date));
    if (mark == null || !mounted || mark == markOf(_marks, date)) return;
    _apply(date, mark);
  }

  Future<void> _submit(AvailabilityPeriodOut period) async {
    setState(() {
      _submitting = true;
      _submitError = null;
    });
    try {
      final sent = await ref
          .read(apiProvider)
          .availability
          .submitMyAvailability(
            body: PeriodRefIn(companyId: widget.companyId, periodId: period.id),
          );
      if (mounted) setState(() => _submittedAt = sent.submittedAt);
    } catch (error) {
      if (mounted) setState(() => _submitError = error);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _refresh() async {
    // Unsaved marks would be lost: they are written first ("Zapisz jeszcze raz"), and the pull says why it waits.
    if (_status != _SaveStatus.saved) {
      final failed = _status == _SaveStatus.failed;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(
          SnackBar(
            content: Text(
              failed ? 'Masz niezapisane zmiany. Zapisz je, zanim odświeżysz.' : 'Jeszcze zapisuję. Odśwież za chwilę.',
            ),
            backgroundColor: failed ? AppColors.cannot : null,
            behavior: SnackBarBehavior.floating,
            action: failed
                ? SnackBarAction(
                    label: 'Zapisz jeszcze raz',
                    textColor: AppColors.accentInk,
                    onPressed: () => _send(Map.of(_failed)),
                  )
                : null,
          ),
        );
      return;
    }
    ref.invalidate(myAvailabilityProvider(widget.companyId));
    final key = (companyId: widget.companyId, month: widget.month);
    ref.invalidate(myCalendarProvider(key));
    await ref.read(myCalendarProvider(key).future);
  }

  @override
  Widget build(BuildContext context) {
    final initial = widget.initial;
    final period = initial.period;
    final editable = _editable;
    final open = _dates.where((date) => !_locked.contains(date)).toList();
    final counts = countStates(_marks, open);
    final todayIso = toIsoDate(ref.read(clockProvider)());
    final arranged = _dates.any(
      (date) => _locked.contains(date) && date.compareTo(todayIso) >= 0 && !_unpublished.contains(date),
    );
    final preparing = _dates.any(_unpublished.contains);
    const muted = TextStyle(fontSize: 14, color: AppColors.inkMuted);
    const gap = SizedBox(height: 16);
    const autosave = Text('Wszystko zapisuje się samo. Dni, których nie ruszysz, zostają jako „Mogę”.', style: muted);

    return TabScreen(
      title: _title,
      onRefresh: _refresh,
      bottom: editable
          ? StateBar(
              tool: _hoursTool ? null : _tool,
              onChanged: (state) => setState(() {
                _tool = state;
                _hoursTool = false;
              }),
            )
          : null,
      children: [
        widget.pager(busy: _status == _SaveStatus.saving),
        gap,
        _PeriodNote(period: period, readOnly: widget.readOnly, today: widget.today),
        if (editable) ...[const SizedBox(height: 8), _SaveIndicator(status: _status)],
        if (initial.locationNames.length > 1) ...[
          gap,
          Text(
            'Pracujesz w kilku lokalach (${initial.locationNames.join(', ')}). Dyspozycje są wspólne: widzą je '
            'kierownicy każdego z nich, a „Wyślij kierownikowi” wysyła je do wszystkich, które o nie proszą w tych '
            'dniach.',
            style: muted,
          ),
        ],
        if (preparing) ...[
          gap,
          Text(
            'Grafik na ${arranged ? 'część szarych dni' : 'szare dni'} jest w przygotowaniu. Zobaczysz go w Moim '
            'grafiku, gdy kierownik go opublikuje.${arranged ? '' : ' Jeśli coś Ci wypadło, skontaktuj się z kierownikiem.'}',
            style: muted,
          ),
        ],
        if (arranged) ...[
          gap,
          Text(
            '${preparing ? 'Na pozostałe szare dni grafik jest już opublikowany.' : 'Na szare dni grafik jest już opublikowany.'} '
            '${widget.readOnly ? 'Jeśli coś Ci wypadło, skontaktuj się z kierownikiem.' : 'Jeśli masz opublikowaną zmianę, która jeszcze się nie zaczęła, możesz ją oddać w Moim grafiku. W pozostałych przypadkach skontaktuj się z kierownikiem.'}',
            style: muted,
          ),
        ],
        if (_status == _SaveStatus.failed) ...[
          gap,
          InlineError(_saveError ?? networkProblem),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: () => _send(Map.of(_failed)), child: const Text('Zapisz jeszcze raz')),
        ],
        gap,
        AvailabilityCalendar(
          start: initial.start,
          end: initial.end,
          marks: _marks,
          disabled: !editable,
          locked: _locked,
          onTapDay: _tapDay,
        ),
        _DaysWithHours(marks: _marks, dates: _dates, locked: _locked, editable: editable, onOpen: _openDay),
        if (open.isNotEmpty) ...[
          gap,
          Semantics(
            liveRegion: true,
            child: Wrap(
              spacing: 14,
              runSpacing: 4,
              children: [
                for (final state in [AvailabilityState.prefer, AvailabilityState.neutral, AvailabilityState.cannot])
                  Text.rich(
                    TextSpan(
                      text: '${state.label}: ',
                      children: [
                        TextSpan(
                          text: '${counts[state]}',
                          style: const TextStyle(
                            fontWeight: FontWeight.w800,
                            color: AppColors.ink,
                            fontFeatures: [FontFeature.tabularFigures()],
                          ),
                        ),
                      ],
                    ),
                    style: muted,
                  ),
              ],
            ),
          ),
        ],
        if (editable) ...[
          gap,
          ChoiceBox(
            chosen: _hoursTool,
            onTap: () => setState(() => _hoursTool = !_hoursTool),
            minHeight: touchMain,
            alignment: Alignment.centerLeft,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(
              children: [
                const Icon(Icons.schedule, size: 26, color: AppColors.accent),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Godziny dnia', style: TextStyle(fontWeight: FontWeight.w600)),
                      Text(
                        _hoursTool
                            ? 'Stuknij dzień w kalendarzu. Stuknij tu, żeby wrócić.'
                            : 'Gdy możesz tylko przez część dnia',
                        style: muted,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          gap,
          if (period == null)
            autosave
          else if (_submittedAt != null)
            _Sent(at: _submittedAt!)
          else ...[
            FilledButton(
              onPressed: _submitting || _status != _SaveStatus.saved ? null : () => _submit(period),
              child: const Text('Wyślij kierownikowi'),
            ),
            const SizedBox(height: 8),
            autosave,
            if (_submitError != null) ...[
              const SizedBox(height: 8),
              InlineError(errorMessage(_submitError, networkProblem)),
            ],
          ],
        ],
      ],
    );
  }
}

/// What the manager is waiting for, if anything.
class _PeriodNote extends StatelessWidget {
  const _PeriodNote({required this.period, required this.readOnly, required this.today});

  final AvailabilityPeriodOut? period;
  final bool readOnly;
  final DateTime today;

  @override
  Widget build(BuildContext context) {
    final period = this.period;
    final InlineSpan text;
    if (readOnly) {
      text = const TextSpan(
        text: 'Firma ma teraz wstrzymany dostęp do aplikacji, więc nic nie zaznaczysz. Grafik nadal widać.',
      );
    } else if (period == null) {
      text = const TextSpan(
        text: 'Zaznacz, kiedy możesz pracować w kolejnych miesiącach. Kierownik zobaczy to, gdy będzie układać grafik.',
      );
    } else {
      final deadline = parseDate(period.deadline);
      final when = periodWords(period.start, period.end);
      text = toIsoDate(today).compareTo(period.deadline) > 0
          ? TextSpan(
              text:
                  'Zaznacz, kiedy możesz pracować $when. Termin minął ${dayAndMonth(deadline)}, ale kierownik nie '
                  'ułożył jeszcze grafiku, więc nadal możesz zmieniać.',
            )
          : TextSpan(
              children: [
                TextSpan(text: 'Zaznacz, kiedy możesz pracować $when. Masz czas do '),
                TextSpan(
                  text: '${weekdayGenitive(deadline)} ${dayAndMonth(deadline)}',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                ),
                const TextSpan(text: '. Potem kierownik ułoży grafik.'),
              ],
            );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(AppRadius.md)),
      child: Text.rich(text, style: const TextStyle(fontSize: 14)),
    );
  }
}

class _SaveIndicator extends StatelessWidget {
  const _SaveIndicator({required this.status});

  final _SaveStatus status;

  @override
  Widget build(BuildContext context) {
    final Widget content = switch (status) {
      _SaveStatus.saving => const Text('Zapisuję…', style: TextStyle(fontSize: 14, color: AppColors.inkMuted)),
      _SaveStatus.failed => const Text(
        'Nie zapisano',
        style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.cannot),
      ),
      _SaveStatus.saved => const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.check, size: 16, color: AppColors.prefer),
          SizedBox(width: 4),
          Text(
            'Zapisane',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.prefer),
          ),
        ],
      ),
    };
    return Semantics(
      liveRegion: true,
      child: Align(alignment: Alignment.centerRight, child: content),
    );
  }
}

/// "Wysłane do kierownika 20 listopada…" after "Wyślij kierownikowi".
class _Sent extends StatelessWidget {
  const _Sent({required this.at});

  final DateTime at;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.preferSoft,
        border: Border.all(color: AppColors.prefer, width: 2),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 2),
            child: Icon(Icons.check, size: 22, color: AppColors.prefer),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Wysłane do kierownika ${dayAndMonth(at.toLocal())}. Dopóki kierownik nie ułoży grafiku, możesz jeszcze '
              'coś zmienić. Zapisuje się samo.',
              style: const TextStyle(color: AppColors.prefer),
            ),
          ),
        ],
      ),
    );
  }
}

/// What a tap marks. It stays at the bottom of the screen while the calendar scrolls, so the chosen state is always
/// in sight. A short screen gets a lower bar (icon beside the word, no line above).
class StateBar extends StatelessWidget {
  const StateBar({super.key, required this.tool, required this.onChanged});

  /// Null while "Godziny dnia" is on.
  final AvailabilityState? tool;
  final ValueChanged<AvailabilityState> onChanged;

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).height < 800;
    final hours = tool == null;
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.paper,
        border: Border(top: BorderSide(color: AppColors.line)),
      ),
      padding: EdgeInsets.fromLTRB(gutter, compact ? 6 : 8, gutter, compact ? 6 : 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (hours || !compact) ...[
            Text(
              hours ? 'Stuknij dzień, żeby ustawić godziny.' : 'Wybierz, a potem zaznacz dni:',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 6),
          ],
          StateButtons(value: tool, onChanged: onChanged, compact: compact),
        ],
      ),
    );
  }
}

/// Days marked with hours, written out, so the hours can be read and changed without hunting in the grid.
class _DaysWithHours extends StatelessWidget {
  const _DaysWithHours({
    required this.marks,
    required this.dates,
    required this.locked,
    required this.editable,
    required this.onOpen,
  });

  final Marks marks;
  final List<String> dates;
  final Set<String> locked;
  final bool editable;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    final withHours = dates.where((date) => hasHours(markOf(marks, date))).toList();
    if (withHours.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            header: true,
            child: const Text('Dni z godzinami', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          ),
          const SizedBox(height: 8),
          Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: AppColors.surface,
              border: Border.all(color: AppColors.line),
              borderRadius: BorderRadius.circular(AppRadius.md),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final (i, date) in withHours.indexed)
                  Container(
                    decoration: BoxDecoration(
                      border: i == 0 ? null : const Border(top: BorderSide(color: AppColors.grid)),
                    ),
                    padding: const EdgeInsets.fromLTRB(14, 6, 6, 6),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(dayTitle(parseDate(date)), style: const TextStyle(fontWeight: FontWeight.w600)),
                              Text(
                                describeMark(markOf(marks, date)),
                                style: const TextStyle(fontSize: 14, color: AppColors.inkMuted),
                              ),
                            ],
                          ),
                        ),
                        if (editable && !locked.contains(date))
                          TextButton(onPressed: () => onOpen(date), child: const Text('Zmień')),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
