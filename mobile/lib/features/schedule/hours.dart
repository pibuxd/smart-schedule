// Other hours of a shift (overtime, leaving early): the website's `features/schedule/hours.ts`, with the same tests.

import '../../api/generated/exports.dart';

final _time = RegExp(r'^([01]?\d|2[0-3]):([0-5]\d)$');

/// "06:00" / "6:00" is a time of day; "" or "25:00" is not.
bool isTime(String value) => _time.hasMatch(value.trim());

int _minutesOfDay(String value) {
  final match = _time.firstMatch(value.trim())!;
  return int.parse(match.group(1)!) * 60 + int.parse(match.group(2)!);
}

/// "6:00" or "06:00:00" -> "06:00", the form the server takes and sends.
String normalTime(String value) {
  final parts = value.trim().split(':');
  return '${parts[0].padLeft(2, '0')}:${parts[1].padLeft(2, '0')}';
}

/// Minutes from `start` to `end` (wall-clock times); an end before the start is the next day, as in the shift settings.
int minutesBetween(String start, String end) {
  final diff = _minutesOfDay(end) - _minutesOfDay(start);
  return diff > 0 ? diff : diff + 24 * 60;
}

/// 90 -> "1 h 30 min", 120 -> "2 h", 45 -> "45 min" (the sign is dropped).
String lengthText(int minutes) {
  final all = minutes.abs();
  final hours = all ~/ 60;
  final rest = all % 60;
  if (hours > 0 && rest > 0) return '$hours h $rest min';
  return hours > 0 ? '$hours h' : '$rest min';
}

/// +60 -> "nadgodziny: +1 h", -120 -> "krócej o 2 h", 0 -> "tyle, ile w grafiku".
String differenceText(int minutes) {
  if (minutes > 0) return 'nadgodziny: +${lengthText(minutes)}';
  if (minutes < 0) return 'krócej o ${lengthText(minutes)}';
  return 'tyle, ile w grafiku';
}

/// The same with a capital letter, for a line of its own.
String differenceSentence(int minutes) {
  final text = differenceText(minutes);
  return text[0].toUpperCase() + text.substring(1);
}

String _pad(int value) => value.toString().padLeft(2, '0');

/// The wall-clock time of [moment] where the shift is ("Wychodzę teraz"), whatever zone the phone is in. The
/// location's offset is the difference between the shift's start on its clock (`start_time`) and in UTC (`start_at`).
String locationClockTime(DateTime moment, MyShiftOut shift) {
  final start = shift.startAt.toUtc();
  var offset = _minutesOfDay(shortTimeOf(shift.startTime)) - (start.hour * 60 + start.minute);
  if (offset > 14 * 60) offset -= 24 * 60;
  if (offset < -12 * 60) offset += 24 * 60;
  final there = moment.toUtc().add(Duration(minutes: offset));
  return '${_pad(there.hour)}:${_pad(there.minute)}';
}

/// "06:00:00" -> "06:00" (the seconds dropped, for [isTime]).
String shortTimeOf(String value) {
  final parts = value.split(':');
  return '${parts[0]}:${parts[1]}';
}
