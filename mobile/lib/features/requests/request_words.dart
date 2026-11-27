// The words around a request, from the website's `RequestsSection.tsx` and `EmployeeChat.tsx`, with the same tests.

import '../../api/generated/exports.dart';
import '../../shared/dates.dart';
import 'requests_data.dart';

/// Requests that count: understood by the assistant (they reach the generator) or left for the manager.
bool isSaved(MyRequestOut request) =>
    request.status == MyRequestOutStatus.interpreted || request.status == MyRequestOutStatus.needsManager;

/// A lasting request written for an earlier month: it counts here too, but belongs to that month's chat.
bool isCarried(MyRequestOut request) => request.carriedFrom != null;

/// "14.12" for "2026-12-14".
String shortDate(String iso) => '${int.parse(iso.substring(8, 10))}.${iso.substring(5, 7)}';

/// "9:00–11:00", "od 10:00", "do 11:00", "9:00–11:00 i 14:00–16:00"; "" for the whole day.
String markHours(CannotMarkOut mark) {
  final hours = mark.hours ?? const [];
  if (hours.isNotEmpty) return windowsWords(hours);
  final from = mark.fromTime == null ? null : shortTime(mark.fromTime!);
  final to = mark.toTime == null ? null : shortTime(mark.toTime!);
  if (from != null && to != null) return '$from–$to';
  if (from != null) return 'od $from';
  return to == null ? '' : 'do $to';
}

/// A summary inside a sentence: no full stop, lower case (unless it starts with "Ty").
String clause(String summary) {
  var text = summary.trim();
  if (text.endsWith('.')) text = text.substring(0, text.length - 1);
  return text.startsWith('Ty ') || text.isEmpty ? text : '${text[0].toLowerCase()}${text.substring(1)}';
}

/// What the generator gets from an understood request. Hours someone cannot work ("nie mogę od 9 do 11") are only
/// marked in the calendar, so they count only after the button (tests of PR #82, 26.11.2026).
String generatorWords(MyRequestOut request, {required bool marked}) {
  final parts = request.parts ?? const [];
  final generator = parts.where((part) => !part.calendarOnly).toList();
  final later = request.lasting ? ', także w kolejnych miesiącach' : '';
  if (generator.length == parts.length) {
    return 'Generator grafiku spróbuje to spełnić$later. Kalendarz się nie zmienia.';
  }
  final hours = marked
      ? 'Godziny, w których nie możesz, zaczną obowiązywać dopiero po zaznaczeniu w kalendarzu przyciskiem niżej.'
      : 'Godziny, w których nie możesz, obowiązują tak, jak są zaznaczone w kalendarzu.';
  if (generator.isEmpty) return 'Generator nie dostaje tej prośby. $hours';
  return 'Generator grafiku spróbuje spełnić$later: ${generator.map((part) => clause(part.summary)).join('; ')}. '
      '$hours';
}

/// "do 9:00 i od 11:00", "do 18:00", "od 10:00", "6:00–22:00": the hours left to work on those days.
String windowsWords(List<WindowOut> windows) => windows
    .map(
      (window) => window.start.startsWith('00:00')
          ? 'do ${shortTime(window.end)}'
          : window.end.startsWith('00:00')
          ? 'od ${shortTime(window.start)}'
          : '${shortTime(window.start)}–${shortTime(window.end)}',
    )
    .join(' i ');

/// The calendar days the button writes: "nie mogę" for a whole day, otherwise "mogę" (or "chętnie") in the windows.
List<DayIn> markedDays(CannotMarkOut mark) {
  final windows = mark.windows ?? const [];
  return [
    for (final date in mark.days)
      if (windows.isEmpty)
        DayIn(date: date, state: DayInState.cannot)
      else
        DayIn(
          date: date,
          state: (mark.preferDays ?? const []).contains(date) ? DayInState.prefer : DayInState.neutral,
          fromTime: windows[0].start,
          toTime: windows[0].end,
          fromTime2: windows.length > 1 ? windows[1].start : null,
          toTime2: windows.length > 1 ? windows[1].end : null,
          oneShift: windows.length > 1 && (mark.oneShiftDays ?? const []).contains(date),
        ),
  ];
}

/// "Prośby na grudzień 2026.": which month (or period) a request written now goes to, so a message written on another
/// screen is not taken for a different month. Null when the period's dates are not at hand.
String? scopeLine(ChatScope scope, AvailabilityPeriodOut? period) {
  String month(String iso) => monthName(iso.substring(0, 7)).toLowerCase();
  if (scope.periodId == null && scope.month != null) return 'Prośby na ${month(scope.month!)}.';
  if (period == null || period.id != scope.periodId) return null;
  final words = periodWords(period.start, period.end);
  return 'Prośby na ${words.startsWith('w ') ? month(period.start) : words}.';
}

/// "w grudniu" (or "1–7 grudnia"): the month or period of the chat, for the choice "Tylko w grudniu" / "Na stałe".
String onlyWords(ChatScope scope, AvailabilityPeriodOut? period) {
  if (scope.periodId == null && scope.month != null) return inMonth(scope.month!);
  if (period != null && period.id == scope.periodId) return periodWords(period.start, period.end);
  return 'ten okres';
}
