import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/features/availability/marks.dart';
import 'package:grafikomat/shared/dates.dart';

// The website's `marks.test.ts` and the month helpers of `dates.ts`, with the same cases.

void main() {
  test('describes hours in plain words, including nights', () {
    expect(
      describeMark(const Mark(AvailabilityState.prefer, from: '22:00', to: '06:00')),
      'chętnie, tylko 22:00–06:00 (do rana)',
    );
    expect(describeMark(const Mark(AvailabilityState.cannot)), 'nie mogę');
    // "Nie mogę od 9 do 11" is marked as "mogę do 9:00 lub od 11:00" ("nie mogę" is always the whole day).
    const rest = Mark(AvailabilityState.neutral, from: '00:00', to: '09:00', from2: '11:00', to2: '00:00');
    expect(describeMark(rest), 'mogę, tylko do 09:00 lub od 11:00');
    expect(cellHours(rest), 'do 9/od 11');
    expect(describeMark(const Mark(AvailabilityState.prefer, from: '14:00', to: '00:00')), 'chętnie, tylko od 14:00');
    expect(cellHours(const Mark(AvailabilityState.prefer, from: '14:00', to: '22:30')), '14–22:30');
    expect(cellHours(Mark.neutral), isNull);
    const two = Mark(AvailabilityState.neutral, from: '06:00', to: '10:00', from2: '16:00', to2: '22:00');
    expect(describeMark(two), 'mogę, tylko 06:00–10:00 lub 16:00–22:00');
    const oneShift = Mark(
      AvailabilityState.neutral,
      from: '06:00',
      to: '10:00',
      from2: '16:00',
      to2: '22:00',
      oneShift: true,
    );
    expect(describeMark(oneShift), 'mogę, tylko 06:00–10:00 albo 16:00–22:00 (jedna zmiana)');
    expect(cellHours(two), '6–10/16–22');
  });

  test('lays the period out in Monday-first weeks', () {
    final weeks = calendarWeeks('2026-12-01', '2026-12-31');
    expect(weeks, hasLength(5));
    expect(weeks[0][0], isNull); // 1 December 2026 is a Tuesday
    expect(weeks[0][1], '2026-12-01');
    expect(weeks[4].nonNulls, ['2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31']);
  });

  test('sends a day the way the server takes it', () {
    expect(toDayIn('2026-12-01', const Mark(AvailabilityState.cannot)).toJson(), {
      'date': '2026-12-01',
      'state': 'cannot',
      'one_shift': false,
    });
    // A second window is sent only whole; "albo" only with one.
    const half = Mark(AvailabilityState.neutral, from: '06:00', to: '10:00', from2: '16:00', oneShift: true);
    expect(toDayIn('2026-12-01', half).toJson(), {
      'date': '2026-12-01',
      'state': 'neutral',
      'from_time': '06:00',
      'to_time': '10:00',
      'one_shift': false,
    });
  });

  test('names months and periods', () {
    expect(monthName('2026-12'), 'Grudzień 2026');
    expect(addMonths('2026-12', 1), '2027-01');
    expect(addMonths('2026-01', -1), '2025-12');
    expect(addMonths('2026-11', 12), '2027-11');
    expect(monthBounds('2027-02'), (start: '2027-02-01', end: '2027-02-28'));
    expect(periodWords('2026-12-01', '2026-12-31'), 'w grudniu');
    expect(periodWords('2026-12-07', '2026-12-13'), '7–13 grudnia');
    expect(periodWords('2026-12-28', '2027-01-03'), '28 grudnia – 3 stycznia');
    expect(compactTime('14:00'), '14');
    expect(compactTime('06:30'), '6:30');
    expect(spanHours('20:00', '16:00'), 20);
    expect(spanHours('22:00', '06:30'), 8.5);
  });
}
