// The list under the nearest shift in "Mój grafik": the website's `features/schedule/rows.ts`, with the same tests.

import '../../api/generated/exports.dart';
import '../../shared/dates.dart';

sealed class ScheduleRow {
  const ScheduleRow(this.key);
  final String key;
}

/// "Tydzień 16–22 listopada" at each new week.
class WeekRow extends ScheduleRow {
  const WeekRow(super.key, this.label);
  final String label;
}

class ShiftRow extends ScheduleRow {
  ShiftRow(this.shift, {required this.showDate}) : super(shift.id);
  final MyShiftOut shift;

  /// The second shift of a day leaves the date out.
  final bool showDate;
}

class OffRow extends ScheduleRow {
  const OffRow(super.key, this.date);
  final DateTime date;
}

/// A run of days outside every published schedule: "grafiku jeszcze nie ma", never "Wolne".
class UnpublishedRow extends ScheduleRow {
  UnpublishedRow(super.key, this.from, this.to);
  final DateTime from;
  DateTime to;
}

/// All days after the first shift up to the end of the published schedule (or the last shift, if later): shifts, days
/// off, and a line at each new week. A free last day of the month is shown too. A day without a shift is a day off
/// only inside a published schedule ([published]); a run of days outside them is one line saying the schedule is not
/// out yet.
List<ScheduleRow> buildRows(
  MyShiftOut first,
  List<MyShiftOut> shifts, {
  String? publishedUntil,
  List<DaysOut>? published,
}) {
  final rows = <ScheduleRow>[];
  final byDate = <String, List<MyShiftOut>>{};
  for (final shift in shifts) {
    byDate.putIfAbsent(shift.date, () => []).add(shift);
  }
  final lastShift = parseDate((shifts.isEmpty ? first : shifts.last).date);
  final until = publishedUntil == null ? lastShift : parseDate(publishedUntil);
  final last = until.isAfter(lastShift) ? until : lastShift;
  bool isPublished(String iso) =>
      published == null || published.any((span) => span.start.compareTo(iso) <= 0 && iso.compareTo(span.end) <= 0);
  String mondayOf(DateTime date) => toIsoDate(addDays(date, -weekdayIndex(date)));
  var week = mondayOf(parseDate(first.date));
  UnpublishedRow? gap;
  var day = addDays(parseDate(first.date), 1);
  while (!day.isAfter(last)) {
    final iso = toIsoDate(day);
    final todays = byDate[iso];
    if (todays == null && !isPublished(iso)) {
      if (gap != null) {
        gap.to = day;
      } else {
        gap = UnpublishedRow('u-$iso', day, day);
        rows.add(gap);
      }
      day = addDays(day, 1);
      continue;
    }
    gap = null;
    if (mondayOf(day) != week) {
      week = mondayOf(day);
      final monday = parseDate(week);
      rows.add(WeekRow('w-$iso', _weekLabel(monday, addDays(monday, 6))));
    }
    if (todays != null) {
      for (var i = 0; i < todays.length; i++) {
        rows.add(ShiftRow(todays[i], showDate: i == 0));
      }
    } else if (iso != first.date) {
      rows.add(OffRow('o-$iso', day));
    }
    day = addDays(day, 1);
  }
  return rows;
}

String _weekLabel(DateTime monday, DateTime sunday) {
  if (monday.month == sunday.month) return 'Tydzień ${monday.day}–${dayAndMonth(sunday)}';
  return 'Tydzień ${dayAndMonth(monday)} – ${dayAndMonth(sunday)}';
}

/// "Anna Wróbel, Marek Zając i 4 inne osoby": a few names are enough to know who is around.
String coworkersText(List<String> names, {int shown = 3}) {
  if (names.length <= shown + 1) return names.join(', ');
  final rest = names.length - shown;
  final few = rest % 10 >= 2 && rest % 10 <= 4 && (rest % 100 < 12 || rest % 100 > 14);
  return '${names.take(shown).join(', ')} i $rest ${few ? 'inne osoby' : 'innych osób'}';
}

/// "1 zmiana", "3 zmiany", "5 zmian"
String shiftsWord(int n) {
  if (n == 1) return '1 zmiana';
  final last = n % 10;
  final teen = n % 100 >= 12 && n % 100 <= 14;
  return '$n ${last >= 2 && last <= 4 && !teen ? 'zmiany' : 'zmian'}';
}
