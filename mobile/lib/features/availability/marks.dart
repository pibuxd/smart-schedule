// Days as the employee marks them in "Kiedy mogę": the website's `features/availability/marks.ts` and
// `calendar-weeks.ts`, with the same tests.

import '../../api/generated/exports.dart';
import '../../shared/dates.dart';

/// Three states: "nie mogę", "mogę" and "chętnie". [neutral] is "mogę", the state of every day until the employee
/// changes it (shown in light green, never as an empty day). Wishes like "wolę nie" are written as a request.
enum AvailabilityState {
  cannot('cannot', 'Nie mogę'),
  neutral('neutral', 'Mogę'),
  prefer('prefer', 'Chętnie');

  const AvailabilityState(this.value, this.label);

  final String value;
  final String label;

  static AvailabilityState of(String value) =>
      values.firstWhere((state) => state.value == value, orElse: () => AvailabilityState.neutral);
}

/// One day as the employee marked it. Hours are "HH:MM"; an end at or before the start means the next morning. An
/// optional second window ("6–10 lub 16–22"); [oneShift] ("albo") = at most one shift that day.
class Mark {
  const Mark(this.state, {this.from, this.to, this.from2, this.to2, this.oneShift = false});

  final AvailabilityState state;
  final String? from;
  final String? to;
  final String? from2;
  final String? to2;
  final bool oneShift;

  static const neutral = Mark(AvailabilityState.neutral);

  @override
  bool operator ==(Object other) =>
      other is Mark &&
      other.state == state &&
      other.from == from &&
      other.to == to &&
      other.from2 == from2 &&
      other.to2 == to2 &&
      other.oneShift == oneShift;

  @override
  int get hashCode => Object.hash(state, from, to, from2, to2, oneShift);

  @override
  String toString() => 'Mark(${describeMark(this)})';
}

typedef Marks = Map<String, Mark>;

String? _hhmm(String? value) => value == null || value.isEmpty ? null : value.substring(0, 5);

Marks marksFromServer(List<AvailabilityDayOut> days) => {
  for (final day in days)
    day.date: Mark(
      AvailabilityState.of(day.state.toJson()),
      from: _hhmm(day.fromTime),
      to: _hhmm(day.toTime),
      from2: _hhmm(day.fromTime2),
      to2: _hhmm(day.toTime2),
      oneShift: day.oneShift,
    ),
};

Mark markOf(Marks marks, String date) => marks[date] ?? Mark.neutral;

DayIn toDayIn(String date, Mark mark) {
  final two = hasSecondWindow(mark);
  // The server clears a second window that is not sent.
  return DayIn(
    date: date,
    state: DayInState.fromJson(mark.state.value),
    fromTime: mark.from,
    toTime: mark.to,
    fromTime2: two ? mark.from2 : null,
    toTime2: two ? mark.to2 : null,
    oneShift: two && mark.oneShift,
  );
}

bool hasSecondWindow(Mark mark) => mark.from2 != null && mark.to2 != null;

bool hasHours(Mark mark) => mark.from != null || mark.to != null;

/// True when the hours run past midnight into the next morning (an end at 0:00 is midnight, not a night).
bool overnight(Mark mark) =>
    mark.from != null && mark.to != null && mark.to != '00:00' && mark.to!.compareTo(mark.from!) <= 0;

/// One window in words: "14:00–22:00", "do 9:00" (from midnight), "od 11:00" (to midnight).
String windowWords(String? from, String? to, String Function(String) time) {
  if (from == null || from == '00:00') return to == null || to == '00:00' ? '' : 'do ${time(to)}';
  if (to == null || to == '00:00') return 'od ${time(from)}';
  return '${time(from)}–${time(to)}';
}

/// Short label inside a calendar cell: "14–22", "od 14", "do 12", "6–10/16–22", "do 9/od 11".
String? cellHours(Mark mark) {
  if (!hasHours(mark)) return null;
  final first = windowWords(mark.from, mark.to, compactTime);
  return hasSecondWindow(mark) ? '$first/${windowWords(mark.from2, mark.to2, compactTime)}' : first;
}

/// Spoken description, e.g. "chętnie, tylko 14:00–22:00", "mogę, tylko do 9:00 lub od 11:00". "Nie mogę" has no
/// hours: it is always the whole day.
String describeMark(Mark mark) {
  final state = mark.state.label.toLowerCase();
  if (!hasHours(mark) || mark.state == AvailabilityState.cannot) return state;
  String plain(String value) => value;
  var window = '${windowWords(mark.from, mark.to, plain)}${overnight(mark) ? ' (do rana)' : ''}';
  if (hasSecondWindow(mark)) {
    final night = mark.to2 != '00:00' && mark.to2!.compareTo(mark.from2!) <= 0;
    final second = '${windowWords(mark.from2, mark.to2, plain)}${night ? ' (do rana)' : ''}';
    window = mark.oneShift ? '$window albo $second (jedna zmiana)' : '$window lub $second';
  }
  return '$state, tylko $window';
}

Map<AvailabilityState, int> countStates(Marks marks, Iterable<String> dates) {
  final counts = {for (final state in AvailabilityState.values) state: 0};
  for (final date in dates) {
    counts[markOf(marks, date).state] = counts[markOf(marks, date).state]! + 1;
  }
  return counts;
}

/// Monday-first weeks covering the period; `null` = a day outside the period.
List<List<String?>> calendarWeeks(String start, String end) {
  final first = parseDate(start);
  final last = parseDate(end);
  final weeks = <List<String?>>[];
  var day = addDays(first, -weekdayIndex(first));
  while (!day.isAfter(last)) {
    final week = <String?>[];
    for (var i = 0; i < 7; i++) {
      week.add(!day.isBefore(first) && !day.isAfter(last) ? toIsoDate(day) : null);
      day = addDays(day, 1);
    }
    weeks.add(week);
  }
  return weeks;
}
