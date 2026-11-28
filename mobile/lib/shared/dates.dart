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
