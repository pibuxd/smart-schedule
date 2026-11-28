import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/api/generated/exports.dart';
import 'package:grafikomat/features/schedule/hours.dart';
import 'package:grafikomat/features/schedule/hours_sheet.dart';
import 'package:grafikomat/features/schedule/rows.dart';
import 'package:grafikomat/shared/dates.dart';
import 'package:grafikomat/shared/money.dart';

// The website's tests of `rows.ts`, `hours.ts`, `dates.ts` and `money.ts`, with the same cases.

MyShiftOut shift(String date, {String? id}) => MyShiftOut.fromJson({
  'id': id ?? date,
  'date': date,
  'start_at': '${date}T06:00:00+01:00',
  'end_at': '${date}T14:00:00+01:00',
  'start_time': '06:00',
  'end_time': '14:00',
  'hours': 8,
  'location_name': 'Wieliczka – Rynek',
  'position_name': 'Sprzedawca',
  'shift_type_name': 'Ranna',
  'away': false,
  'coworkers': <String>[],
});

String kinds(List<ScheduleRow> rows) => rows
    .map(
      (r) => switch (r) {
        WeekRow() => 'week',
        ShiftRow() => 'shift',
        OffRow() => 'off',
        UnpublishedRow() => 'unpublished',
      },
    )
    .join(' ');

void main() {
  group('Mój grafik list', () {
    test('shows days off between shifts and a line at each new week', () {
      final rows = buildRows(shift('2026-11-13'), [shift('2026-11-14'), shift('2026-11-16')]);
      expect(kinds(rows), 'shift off week shift');
      expect((rows[2] as WeekRow).label, 'Tydzień 16–22 listopada');
    });

    test('goes on to the end of the published schedule, so a free last day is shown', () {
      expect(kinds(buildRows(shift('2026-12-29'), [shift('2026-12-30')], publishedUntil: '2026-12-31')), 'shift off');
      expect(kinds(buildRows(shift('2026-12-30'), [], publishedUntil: '2026-12-31')), 'off');
    });

    test('calls a day off only a day of a published schedule', () {
      final published = [
        const DaysOut(start: '2026-11-26', end: '2026-11-30'),
        const DaysOut(start: '2027-02-01', end: '2027-02-28'),
      ];
      final rows = buildRows(
        shift('2026-11-30'),
        [shift('2027-02-01')],
        publishedUntil: '2027-02-02',
        published: published,
      );
      expect(kinds(rows), 'unpublished week shift off');
      final gap = rows[0] as UnpublishedRow;
      expect(gap.from, DateTime(2026, 12, 1));
      expect(gap.to, DateTime(2027, 1, 31));
      expect((rows[1] as WeekRow).label, 'Tydzień 1–7 lutego');
    });

    test('names a few coworkers and counts the rest with the right Polish form', () {
      expect(coworkersText(['Anna', 'Marek']), 'Anna, Marek');
      expect(coworkersText(['A', 'B', 'C', 'D', 'E']), 'A, B, C i 2 inne osoby');
      expect(coworkersText(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']), 'A, B, C i 5 innych osób');
      expect(shiftsWord(1), '1 zmiana');
      expect(shiftsWord(3), '3 zmiany');
      expect(shiftsWord(12), '12 zmian');
      expect(shiftsWord(22), '22 zmiany');
    });
  });

  group('hours', () {
    test('reads times of day', () {
      expect(isTime('06:00'), isTrue);
      expect(isTime('6:30'), isTrue);
      expect(isTime('23:59'), isTrue);
      expect(isTime(''), isFalse);
      expect(isTime('24:00'), isFalse);
      expect(isTime('6'), isFalse);
    });

    test('counts a night shift into the next day', () {
      expect(minutesBetween('06:00', '14:30'), 510);
      expect(minutesBetween('22:00', '06:00'), 480);
      expect(minutesBetween('06:00', '06:00'), 24 * 60);
    });

    test('says how much longer or shorter in plain words', () {
      expect(lengthText(90), '1 h 30 min');
      expect(lengthText(-120), '2 h');
      expect(lengthText(45), '45 min');
      expect(differenceText(60), 'nadgodziny: +1 h');
      expect(differenceText(-150), 'krócej o 2 h 30 min');
      expect(differenceText(0), 'tyle, ile w grafiku');
      expect(differenceSentence(-120), 'Krócej o 2 h');
    });

    test("writes the time on the location's clock, whatever zone the phone is in", () {
      final moment = DateTime.utc(2026, 11, 13, 10, 15);
      expect(locationClockTime(moment, shift('2026-11-13')), '11:15');
      final summer = MyShiftOut.fromJson({
        ...shift('2026-07-13').toJson(),
        'start_at': '2026-07-13T06:00:00+02:00',
        'end_at': '2026-07-13T14:00:00+02:00',
      });
      expect(locationClockTime(moment, summer), '12:15');
    });

    test('puts the colon into a time typed on the number keyboard', () {
      expect(formatTimeDigits('1530'), '15:30');
      expect(formatTimeDigits('153'), '15:3');
      expect(formatTimeDigits('15'), '15');
      expect(formatTimeDigits('600'), '6:00');
      expect(formatTimeDigits('6:00'), '6:00');
      expect(formatTimeDigits('06:00'), '06:00');
      expect(formatTimeDigits('245'), '2:45');
      expect(formatTimeDigits('2315'), '23:15');
      expect(formatTimeDigits(''), '');
      expect(normalTime('6:00'), '06:00');
      expect(normalTime('06:00:00'), '06:00');
    });
  });

  group('dates and money', () {
    test('says days the way people do', () {
      final today = DateTime(2026, 11, 12);
      expect(relativeDay(DateTime(2026, 11, 12), today), 'dzisiaj');
      expect(relativeDay(DateTime(2026, 11, 13), today), 'jutro');
      expect(relativeDay(DateTime(2026, 11, 14), today), 'pojutrze');
      expect(relativeDay(DateTime(2026, 11, 17), today), 'za 5 dni');
      expect(dayTitle(DateTime(2026, 12, 4)), 'piątek 4 grudnia');
      expect(inMonth('2026-11'), 'w listopadzie');
      expect(shortTime('06:00:00'), '6:00');
      expect(hoursText(112), '112 godz.');
      expect(hoursText(7.5), '7,5 godz.');
      // Across the change of the clocks, a day is still a day.
      expect(toIsoDate(addDays(DateTime(2026, 10, 24), 1)), '2026-10-25');
      expect(toIsoDate(addDays(DateTime(2026, 10, 25), 1)), '2026-10-26');
    });

    test('writes złoty like the website', () {
      expect(moneyText(3768), '3768,00 zł');
      expect(moneyText(3516.8), '3516,80 zł');
      expect(moneyText(12345.5), '12 345,50 zł');
      expect(moneyText(1234567), '1 234 567,00 zł');
    });
  });
}
