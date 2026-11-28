import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../shared/dates.dart';
import '../../shared/money.dart';
import '../../ui/fold.dart';
import '../../ui/sheet.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../employee/employee_shell.dart';
import 'give_away_sheet.dart';
import 'hours.dart';
import 'hours_sheet.dart';
import 'offers_to_take.dart';
import 'rows.dart';
import 'schedule_data.dart';

const _tabular = [FontFeature.tabularFigures()];

/// "Mój grafik", the website's `MyScheduleScreen`. A tapped push notification opens it on what it is about
/// (`/grafik?dzien=…&oferta=…`, backend `push_path`): [focusDay] (a shift's day, or the first day of a new schedule)
/// outlines that day's shift, or the first day after it; [focusOffer] opens "Zmiany do wzięcia" on a shift someone
/// gives away. The screen's time moves at the start and end of each shift and when the app comes back to the front.
class ScheduleTab extends ConsumerStatefulWidget {
  const ScheduleTab({super.key, this.focusDay, this.focusOffer});

  final String? focusDay;
  final String? focusOffer;

  @override
  ConsumerState<ScheduleTab> createState() => _ScheduleTabState();
}

class _ScheduleTabState extends ConsumerState<ScheduleTab> {
  late DateTime _now = ref.read(clockProvider)();
  late final AppLifecycleListener _lifecycle;
  Timer? _tick;
  Object? _tickPlannedFor;
  // What a tapped notification is about: a day (its shift, a day off, a past shift) or a shift to take.
  final _dayKey = GlobalKey();
  final _offerKey = GlobalKey();
  bool _scrolled = false;

  @override
  void initState() {
    super.initState();
    _lifecycle = AppLifecycleListener(onResume: _resumed);
  }

  @override
  void dispose() {
    _tick?.cancel();
    _lifecycle.dispose();
    super.dispose();
  }

  void _resumed() {
    setState(() => _now = ref.read(clockProvider)());
    refreshSchedule(ref);
  }

  /// Wakes the screen when the next shift starts or ends (at the latest in a day), so "Trwa Twoja zmiana" and
  /// "Minione zmiany" follow the clock while the app stays open.
  void _planTick(List<MyShiftOut> shifts) {
    if (identical(_tickPlannedFor, shifts) && _tick != null) return;
    _tickPlannedFor = shifts;
    _tick?.cancel();
    var delay = const Duration(days: 1);
    for (final shift in shifts) {
      for (final edge in [countedStart(shift), countedEnd(shift)]) {
        final until = edge.difference(_now) + const Duration(milliseconds: 1);
        if (!until.isNegative && until < delay) delay = until;
      }
    }
    _tick = Timer(delay, () {
      if (!mounted) return;
      _tick = null;
      setState(() => _now = ref.read(clockProvider)());
    });
  }

  void _scrollToFocus() {
    if (_scrolled) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final target = (widget.focusOffer != null ? _offerKey : _dayKey).currentContext ?? _dayKey.currentContext;
      if (_scrolled || target == null || !target.mounted) return;
      _scrolled = true;
      Scrollable.ensureVisible(target, alignment: 0.3, duration: const Duration(milliseconds: 250));
    });
  }

  Future<void> _refresh(String companyId) async {
    setState(() => _now = ref.read(clockProvider)());
    refreshSchedule(ref);
    await ref.read(myScheduleProvider(companyId).future);
  }

  @override
  Widget build(BuildContext context) {
    const title = 'Mój grafik';
    final session = ref.watch(sessionProvider);
    final company = session is SessionReady ? session.company : null;
    if (company == null) return const TabScreen(title: title, children: []);
    final schedule = ref.watch(myScheduleProvider(company.id));
    final data = schedule.value;
    final List<Widget> content;
    if (data != null) {
      _planTick(data.shifts);
      content = _content(data, company.id, company.readOnly);
      if (widget.focusDay != null || widget.focusOffer != null) _scrollToFocus();
    } else if (schedule.hasError) {
      content = [
        ErrorView(
          errorMessage(schedule.error, 'Nie udało się wczytać grafiku. Sprawdź internet i spróbuj jeszcze raz.'),
          onRetry: () => ref.invalidate(myScheduleProvider(company.id)),
        ),
      ];
    } else {
      content = const [LoadingView('Wczytuję Twój grafik…')];
    }
    return TabScreen(title: title, onRefresh: () => _refresh(company.id), children: content);
  }

  List<Widget> _content(MyScheduleOut data, String companyId, bool readOnly) {
    final now = _now;
    bool ahead(MyShiftOut shift) => countedEnd(shift).isAfter(now);
    final upcoming = data.shifts.where(ahead).toList();
    final next = upcoming.isEmpty ? null : upcoming.first;
    final rest = upcoming.skip(1).toList();
    // A shift that ended while the screen was open moves to "Minione zmiany" at once (newest first), so
    // "Zgłoś inne godziny" stays at hand right when the work ends.
    final known = {for (final shift in data.recent ?? <MyShiftOut>[]) shift.id};
    final justEnded = data.shifts.where((s) => !ahead(s) && s.canReport && !known.contains(s.id)).toList().reversed;
    final recent = [...justEnded, ...?data.recent];
    final todayIso = toIsoDate(now);
    void Function(MyShiftOut)? give = readOnly ? null : (shift) => showGiveAwaySheet(context, shift);
    void Function(MyShiftOut)? report = readOnly
        ? null
        : (shift) => showHoursSheet(context, shift, ref.read(clockProvider)());
    // "Zgłoś inne godziny" at today's or the running shift; earlier ones are in "Minione zmiany".
    final reportNext = next != null && next.canReport && (next.date == todayIso || !next.startAt.isAfter(now))
        ? report
        : null;

    // Which part shows the day a notification is about: the nearest shift, a later day, or a past shift. A shift
    // that ended today is past too (the manager approved its hours after work), so it wins over the next day's shift.
    final focusDay = widget.focusDay;
    final pastOnDay =
        focusDay != null && focusDay.compareTo(todayIso) <= 0 && recent.any((shift) => shift.date == focusDay);
    final focusNext =
        focusDay != null &&
        next != null &&
        (next.date == focusDay ||
            (!pastOnDay && todayIso.compareTo(focusDay) <= 0 && focusDay.compareTo(next.date) < 0));
    final focusLater = focusDay != null && next != null && focusDay.compareTo(next.date) > 0 ? focusDay : null;
    final focusPast = pastOnDay && !focusNext ? focusDay : null;
    final publishedUntil = data.publishedUntil;

    const gap = SizedBox(height: 20);
    return [
      OffersToTake(companyId: companyId, readOnly: readOnly, focus: widget.focusOffer, focusKey: _offerKey),
      if (next != null)
        _NextShift(
          key: focusNext ? _dayKey : null,
          shift: next,
          now: now,
          focused: focusNext,
          onGive: next.startAt.isAfter(now) ? give : null,
          onReport: reportNext,
        )
      else
        EmptyView(
          title: 'Nie masz jeszcze zmian w grafiku',
          children: [
            const Text('Gdy kierownik opublikuje grafik, zobaczysz tu swoje zmiany i godziny.'),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () => context.go('/kiedy-moge'),
                child: const Text('Zaznacz, kiedy możesz pracować'),
              ),
            ),
          ],
        ),
      if (next != null && (rest.isNotEmpty || (publishedUntil ?? next.date).compareTo(next.date) > 0)) ...[
        gap,
        _UpcomingList(
          first: next,
          shifts: rest,
          publishedUntil: publishedUntil,
          published: data.published,
          focusDay: focusLater,
          focusKey: _dayKey,
          onGive: give,
        ),
      ],
      if (publishedUntil != null) ...[
        gap,
        Text(
          'Grafik jest opublikowany do ${weekdayGenitive(parseDate(publishedUntil))} '
          '${dayAndMonth(parseDate(publishedUntil))}.',
          style: const TextStyle(color: AppColors.inkMuted),
        ),
      ],
      if ((data.preparing ?? []).isNotEmpty) ...[
        gap,
        Text(preparingText(data.preparing!, data.homeLocationName), style: const TextStyle(color: AppColors.inkMuted)),
      ],
      for (final (i, month) in data.months.indexed) ...[
        i == 0 ? gap : const SizedBox(height: 8),
        _MonthTotal(month: month),
      ],
      if (recent.isNotEmpty) ...[
        gap,
        _PastShifts(shifts: recent, onReport: report, focusDay: focusPast, focusKey: _dayKey),
      ],
    ];
  }
}

/// "Grafik od 1 grudnia jest w przygotowaniu": a schedule arranged but not published yet, so its days are locked in
/// "Kiedy mogę" while this screen shows nothing of it. Another location is named.
String preparingText(List<PreparingOut> preparing, String home) {
  final parts = [
    for (final p in preparing)
      'od ${dayAndMonth(parseDate(p.start))}${p.locationName == home ? '' : ' w lokalu ${p.locationName}'}',
  ];
  final when = parts.length > 1 ? '${parts.sublist(0, parts.length - 1).join(', ')} i ${parts.last}' : parts.first;
  return 'Grafik $when jest w przygotowaniu. Zobaczysz tu swoje zmiany, gdy kierownik go opublikuje.';
}

String _timeRange(MyShiftOut shift) => '${shortTime(countedStartTime(shift))}–${shortTime(countedEndTime(shift))}';

String _shiftLine(MyShiftOut shift) {
  final kind = shift.shiftTypeName.isEmpty ? '' : ', ${shift.shiftTypeName.toLowerCase()}';
  return '${shift.positionName}$kind';
}

const _muted = TextStyle(fontSize: 14, color: AppColors.inkMuted);

/// "Razem w listopadzie" and, once the manager has set rates, the pay for the month's published shifts.
class _MonthTotal extends StatelessWidget {
  const _MonthTotal({required this.month});

  final MonthHoursOut month;

  @override
  Widget build(BuildContext context) {
    final pay = month.pay;
    final unpriced = month.unpricedHours;
    final supplements = month.supplementsPay ?? 0;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.ink, width: 2),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(child: Text('Razem ${inMonth(month.month)}')),
              Text(
                hoursText(month.hours),
                style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800, fontFeatures: _tabular),
              ),
            ],
          ),
          if (pay != null) ...[
            const SizedBox(height: 4),
            Row(
              children: [
                const Expanded(child: Text('Wypłata brutto')),
                Text(
                  moneyText(pay),
                  style: const TextStyle(fontWeight: FontWeight.w800, fontFeatures: _tabular),
                ),
              ],
            ),
            if (supplements > 0) Text('W tym dodatki: ${moneyText(supplements)}.', style: _muted),
            if (unpriced > 0)
              Text('Bez ${hoursText(unpriced)}, bo kierownik nie ustawił dla nich stawki.', style: _muted),
          ],
        ],
      ),
    );
  }
}

/// Under a shift: the schedule's hours when others count, and my report waiting for the manager.
class _HoursNote extends StatelessWidget {
  const _HoursNote({required this.shift});

  final MyShiftOut shift;

  @override
  Widget build(BuildContext context) {
    final worked = shift.worked;
    final report = shift.report;
    if (worked == null && report == null) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (worked != null)
          Text(
            'W grafiku ${shortTime(shift.startTime)}–${shortTime(shift.endTime)}, '
            '${differenceText(worked.differenceMinutes)} (${worked.byManager ? 'od kierownika' : 'zatwierdzone'})',
            style: _muted,
          ),
        if (report != null)
          Text(
            'Zgłoszone ${shortTime(report.startTime)}–${shortTime(report.endTime)}: czeka na kierownika',
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.preferNot),
          ),
      ],
    );
  }
}

/// "Oddaj zmianę" next to a shift, or what happens to a shift I am giving away.
class _GiveButton extends StatelessWidget {
  const _GiveButton({required this.shift, required this.onGive, this.wide = false});

  final MyShiftOut shift;
  final void Function(MyShiftOut)? onGive;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final give = onGive;
    if (give == null) return const SizedBox.shrink();
    final status = shift.offerStatus;
    final label = status != null
        ? status == MyShiftOutOfferStatus.claimed
              ? 'Oddajesz: czeka na kierownika'
              : 'Oddajesz, jeszcze nikt się nie zgłosił'
        : wide
        ? 'Oddaj tę zmianę'
        : 'Oddaj';
    final size = Size(wide ? double.infinity : 48, touch);
    if (status != null) {
      return OutlinedButton(
        style: OutlinedButton.styleFrom(minimumSize: size),
        onPressed: () => give(shift),
        child: Text(label),
      );
    }
    return TextButton(
      style: TextButton.styleFrom(
        minimumSize: size,
        padding: wide ? null : const EdgeInsets.symmetric(horizontal: 8),
        textStyle: wide ? null : const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
      ),
      onPressed: () => give(shift),
      child: Text(label),
    );
  }
}

/// The nearest shift, drawn like a page of a tear-off calendar: a big day number to read at arm's length.
class _NextShift extends StatelessWidget {
  const _NextShift({
    super.key,
    required this.shift,
    required this.now,
    required this.focused,
    required this.onGive,
    required this.onReport,
  });

  final MyShiftOut shift;
  final DateTime now;
  final bool focused;
  final void Function(MyShiftOut)? onGive;
  final void Function(MyShiftOut)? onReport;

  @override
  Widget build(BuildContext context) {
    final day = parseDate(shift.date);
    final running = !shift.startAt.isAfter(now);
    final report = onReport;
    return FocusOutline(
      focused: focused,
      child: Semantics(
        container: true,
        label: 'Najbliższa zmiana',
        child: Container(
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: AppColors.surface,
            border: Border.all(color: AppColors.line),
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                color: AppColors.accent,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: DefaultTextStyle.merge(
                  style: const TextStyle(color: AppColors.accentInk, fontWeight: FontWeight.w600, fontSize: 16),
                  child: Row(
                    children: [
                      Expanded(child: Text(running ? 'Trwa Twoja zmiana' : 'Najbliższa zmiana')),
                      Text(relativeDay(day, now)),
                    ],
                  ),
                ),
              ),
              CustomPaint(painter: _TearLine(), size: const Size(double.infinity, 2)),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
                child: Row(
                  children: [
                    ConstrainedBox(
                      constraints: const BoxConstraints(minWidth: 84),
                      child: Column(
                        children: [
                          Text(
                            '${day.day}',
                            style: const TextStyle(
                              fontSize: 56,
                              height: 0.95,
                              fontWeight: FontWeight.w800,
                              color: AppColors.accent,
                              fontFeatures: _tabular,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${weekdayLong(day)}\n${monthGenitive(day)}',
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: AppColors.inkMuted,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            _timeRange(shift),
                            style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800, fontFeatures: _tabular),
                          ),
                          _HoursNote(shift: shift),
                          Text(_shiftLine(shift), style: const TextStyle(fontWeight: FontWeight.w600)),
                          Text('${shift.locationName}${shift.away ? ' (inny lokal)' : ''}', style: _muted),
                          Text(
                            shift.coworkers.isNotEmpty
                                ? 'Z Tobą: ${coworkersText(shift.coworkers)}'
                                : 'Na tej zmianie nie ma nikogo więcej.',
                            style: _muted,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              if (onGive != null || report != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  decoration: const BoxDecoration(
                    border: Border(top: BorderSide(color: AppColors.grid)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _GiveButton(shift: shift, onGive: onGive, wide: true),
                      if (report != null)
                        TextButton(
                          style: TextButton.styleFrom(minimumSize: const Size(double.infinity, touch)),
                          onPressed: () => report(shift),
                          child: Text(
                            shift.report != null ? 'Zgłoszone inne godziny: zmień albo wycofaj' : 'Zgłoś inne godziny',
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The dashed edge under the top of a tear-off calendar page.
class _TearLine extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = AppColors.accent);
    final dash = Paint()..color = AppColors.accentInk.withValues(alpha: 0.55);
    for (var x = 0.0; x < size.width; x += 8) {
      canvas.drawRect(Rect.fromLTWH(x, 0, 4, size.height), dash);
    }
  }

  @override
  bool shouldRepaint(_TearLine oldDelegate) => false;
}

class _DateCell extends StatelessWidget {
  const _DateCell({required this.date});

  final DateTime date;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 52,
      child: Column(
        children: [
          Text(
            '${date.day}',
            style: const TextStyle(fontSize: 21, height: 1.1, fontWeight: FontWeight.w800, fontFeatures: _tabular),
          ),
          Text(
            weekdayShort(date),
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppColors.inkMuted),
          ),
        ],
      ),
    );
  }
}

/// A list in one card, each row under a thin line.
class _Card extends StatelessWidget {
  const _Card({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < children.length; i++)
            DecoratedBox(
              decoration: BoxDecoration(
                border: i == 0 ? null : const Border(top: BorderSide(color: AppColors.grid)),
              ),
              child: children[i],
            ),
        ],
      ),
    );
  }
}

class _UpcomingList extends StatelessWidget {
  const _UpcomingList({
    required this.first,
    required this.shifts,
    required this.publishedUntil,
    required this.published,
    required this.focusDay,
    required this.focusKey,
    required this.onGive,
  });

  final MyShiftOut first;
  final List<MyShiftOut> shifts;
  final String? publishedUntil;
  final List<DaysOut>? published;
  final String? focusDay;
  final GlobalKey focusKey;
  final void Function(MyShiftOut)? onGive;

  @override
  Widget build(BuildContext context) {
    final rows = buildRows(first, shifts, publishedUntil: publishedUntil, published: published);
    // The first day on or after the one a notification is about (its shift, or a day off).
    String? focusRow;
    final day = focusDay;
    if (day != null) {
      for (final row in rows) {
        final last = switch (row) {
          WeekRow() => null,
          ShiftRow(:final shift) => shift.date,
          OffRow(:final date) => toIsoDate(date),
          UnpublishedRow(:final to) => toIsoDate(to),
        };
        if (last != null && last.compareTo(day) >= 0) {
          focusRow = row.key;
          break;
        }
      }
    }
    Widget mark(ScheduleRow row, Widget child) {
      final focused = row.key == focusRow;
      return FocusOutline(key: focused ? focusKey : null, focused: focused, radius: 0, child: child);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(header: true, child: Text('Kolejne dni', style: Theme.of(context).textTheme.titleMedium)),
        const SizedBox(height: 12),
        _Card(
          children: [
            for (final row in rows)
              switch (row) {
                WeekRow(:final label) => Container(
                  color: AppColors.paper,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                  child: Text(
                    label,
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppColors.inkMuted),
                  ),
                ),
                UnpublishedRow(:final from, :final to) => mark(
                  row,
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Text(
                      from == to
                          ? '${dayAndMonth(from)}: grafiku jeszcze nie ma.'
                          : '${dayAndMonth(from)} – ${dayAndMonth(to)}: grafiku jeszcze nie ma.',
                      style: const TextStyle(color: AppColors.inkMuted),
                    ),
                  ),
                ),
                OffRow(:final date) => mark(
                  row,
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Row(
                      children: [
                        _DateCell(date: date),
                        const SizedBox(width: 12),
                        const Text('Wolne', style: TextStyle(color: AppColors.inkMuted)),
                      ],
                    ),
                  ),
                ),
                ShiftRow(:final shift, :final showDate) => mark(row, _ShiftRowView(shift, showDate, onGive)),
              },
          ],
        ),
      ],
    );
  }
}

class _ShiftRowView extends StatelessWidget {
  const _ShiftRowView(this.shift, this.showDate, this.onGive);

  final MyShiftOut shift;
  final bool showDate;
  final void Function(MyShiftOut)? onGive;

  @override
  Widget build(BuildContext context) {
    final details = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _timeRange(shift),
          style: const TextStyle(fontWeight: FontWeight.w800, fontFeatures: _tabular),
        ),
        _HoursNote(shift: shift),
        Text(
          '${_shiftLine(shift)}${shift.away ? ', ${shift.locationName}' : ''}'
          '${shift.coworkers.isNotEmpty ? '. Z Tobą: ${coworkersText(shift.coworkers, shown: 2)}' : ''}',
          style: _muted,
        ),
      ],
    );
    final giving = shift.offerStatus != null;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          showDate ? _DateCell(date: parseDate(shift.date)) : const SizedBox(width: 52),
          const SizedBox(width: 12),
          Expanded(
            child: giving
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      details,
                      const SizedBox(height: 8),
                      _GiveButton(shift: shift, onGive: onGive),
                    ],
                  )
                : details,
          ),
          if (!giving) _GiveButton(shift: shift, onGive: onGive),
        ],
      ),
    );
  }
}

/// The last two weeks: the hours that counted, and "Inne godziny" while I may still report them.
class _PastShifts extends StatelessWidget {
  const _PastShifts({required this.shifts, required this.onReport, required this.focusDay, required this.focusKey});

  final List<MyShiftOut> shifts;
  final void Function(MyShiftOut)? onReport;
  final String? focusDay;
  final GlobalKey focusKey;

  @override
  Widget build(BuildContext context) {
    final waiting = shifts.where((s) => s.report != null).length;
    String? focusId;
    for (final shift in shifts) {
      if (shift.date == focusDay) {
        focusId = shift.id;
        break;
      }
    }
    final report = onReport;
    return Fold(
      title: 'Minione zmiany',
      initiallyOpen: focusId != null,
      status: waiting > 0
          ? TextSpan(
              text: 'czeka: $waiting',
              style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.preferNot),
            )
          : null,
      description: 'Ostatnie dwa tygodnie. Gdy praca trwała dłużej albo krócej niż w grafiku, zgłoś to kierownikowi.',
      child: _Card(
        children: [
          for (final shift in shifts)
            FocusOutline(
              key: shift.id == focusId ? focusKey : null,
              focused: shift.id == focusId,
              radius: 0,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                child: Row(
                  children: [
                    _DateCell(date: parseDate(shift.date)),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            _timeRange(shift),
                            style: const TextStyle(fontWeight: FontWeight.w800, fontFeatures: _tabular),
                          ),
                          _HoursNote(shift: shift),
                          Text('${_shiftLine(shift)}${shift.away ? ', ${shift.locationName}' : ''}', style: _muted),
                        ],
                      ),
                    ),
                    if (report != null && shift.canReport)
                      TextButton(
                        style: TextButton.styleFrom(
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                        ),
                        onPressed: () => report(shift),
                        child: const Text('Inne godziny'),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
