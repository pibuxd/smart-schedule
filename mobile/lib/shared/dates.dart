// Polish date words, written out so they read naturally ("w grudniu", "4 grudnia", "pt"). The same words and cases
// as the website's `frontend/src/lib/dates.ts`, with the same test cases.

const _weekdaysShort = ['pon', 'wt', 'śr', 'czw', 'pt', 'sob', 'niedz'];
const _weekdaysLong = ['poniedziałek', 'wtorek', 'środa', 'czwartek', 'piątek', 'sobota', 'niedziela'];
const _weekdaysGenitive = ['poniedziałku', 'wtorku', 'środy', 'czwartku', 'piątku', 'soboty', 'niedzieli'];
const _monthsGenitive = [
  'stycznia',
  'lutego',
  'marca',
  'kwietnia',
  'maja',
  'czerwca',
  'lipca',
  'sierpnia',
  'września',
  'października',
  'listopada',
  'grudnia',
];
const _monthsNominative = [
  'styczeń',
  'luty',
  'marzec',
  'kwiecień',
  'maj',
  'czerwiec',
  'lipiec',
  'sierpień',
  'wrzesień',
  'październik',
  'listopad',
  'grudzień',
];
const _monthsLocative = [
  'styczniu',
  'lutym',
  'marcu',
  'kwietniu',
  'maju',
  'czerwcu',
  'lipcu',
  'sierpniu',
  'wrześniu',
  'październiku',
  'listopadzie',
  'grudniu',
];

/// "2026-12-04" -> a local date at midnight (no time-zone shifts).
DateTime parseDate(String iso) {
  final parts = iso.substring(0, 10).split('-').map(int.parse).toList();
  return DateTime(parts[0], parts[1], parts[2]);
}

String toIsoDate(DateTime date) =>
    '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

/// Calendar days, not 24-hour steps, so a change of the clocks does not skip or repeat a day.
DateTime addDays(DateTime date, int days) => DateTime(date.year, date.month, date.day + days);

/// Monday = 0 … Sunday = 6.
int weekdayIndex(DateTime date) => date.weekday - 1;

String weekdayShort(DateTime date) => _weekdaysShort[weekdayIndex(date)];
String weekdayLong(DateTime date) => _weekdaysLong[weekdayIndex(date)];

/// "do wtorku": the weekday after "do".
String weekdayGenitive(DateTime date) => _weekdaysGenitive[weekdayIndex(date)];
String monthGenitive(DateTime date) => _monthsGenitive[date.month - 1];

/// "piątek 4 grudnia"
String dayTitle(DateTime date) => '${weekdayLong(date)} ${date.day} ${monthGenitive(date)}';

/// "4 grudnia"
String dayAndMonth(DateTime date) => '${date.day} ${monthGenitive(date)}';

/// "dzisiaj", "jutro", "pojutrze", "za 5 dni"
String relativeDay(DateTime date, DateTime today) {
  final days = parseDate(toIsoDate(date)).difference(parseDate(toIsoDate(today))).inHours / 24;
  final whole = days.round();
  if (whole <= 0) return 'dzisiaj';
  if (whole == 1) return 'jutro';
  if (whole == 2) return 'pojutrze';
  return 'za $whole dni';
}

/// "06:00" or "06:00:00" -> "6:00"
String shortTime(String value) {
  final parts = value.split(':');
  return '${int.parse(parts[0])}:${parts[1]}';
}

/// 112 -> "112 godz.", 7.5 -> "7,5 godz."
String hoursText(num hours) {
  final rounded = (hours * 10).round() / 10;
  final text = rounded == rounded.roundToDouble() ? rounded.toInt().toString() : rounded.toString();
  return '${text.replaceAll('.', ',')} godz.';
}

/// "2026-11" -> "w listopadzie"
String inMonth(String month) => 'w ${_monthsLocative[int.parse(month.substring(5, 7)) - 1]}';

/// Column heads of a Monday-first calendar: "pon" … "niedz".
const weekdayHeaders = _weekdaysShort;

/// "2026-12" -> "Grudzień 2026"
String monthName(String month) {
  final name = _monthsNominative[int.parse(month.substring(5, 7)) - 1];
  return '${name[0].toUpperCase()}${name.substring(1)} ${month.substring(0, 4)}';
}

/// "2026-12-04" -> "2026-12"
String monthOf(String iso) => iso.substring(0, 7);

/// "2026-12" moved by whole months: ("2026-12", 1) -> "2027-01".
String addMonths(String month, int count) {
  final date = DateTime(int.parse(month.substring(0, 4)), int.parse(month.substring(5, 7)) + count);
  return monthOf(toIsoDate(date));
}

/// The first and the last day of a month: "2026-12" -> ("2026-12-01", "2026-12-31").
({String start, String end}) monthBounds(String month) {
  final first = parseDate('$month-01');
  return (start: toIsoDate(first), end: toIsoDate(DateTime(first.year, first.month + 1, 0)));
}

/// Title of a period: "w grudniu" for a whole month, otherwise "7–13 grudnia" or "28 grudnia – 3 stycznia".
String periodWords(String startIso, String endIso) {
  final start = parseDate(startIso);
  final end = parseDate(endIso);
  final wholeMonth = start.day == 1 && addDays(end, 1).day == 1 && start.month == end.month;
  if (wholeMonth) return 'w ${_monthsLocative[start.month - 1]}';
  if (start.month == end.month) return '${start.day}–${end.day} ${monthGenitive(end)}';
  return '${dayAndMonth(start)} – ${dayAndMonth(end)}';
}

/// "14:00" -> "14", "14:30" -> "14:30" (for small labels inside calendar cells).
String compactTime(String value) {
  final parts = value.split(':');
  return parts[1] == '00' ? '${int.parse(parts[0])}' : '${int.parse(parts[0])}:${parts[1]}';
}

/// Hours from `from` to `to`, going past midnight when `to` is earlier ("20:00"–"16:00" = 20).
num spanHours(String from, String to) {
  int minutes(String value) => int.parse(value.substring(0, 2)) * 60 + int.parse(value.substring(3, 5));
  final span = (minutes(to) - minutes(from) + 24 * 60) % (24 * 60);
  final hours = (span / 60 * 10).round() / 10;
  return hours == hours.roundToDouble() ? hours.toInt() : hours;
}
