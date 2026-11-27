import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/client.dart';
import '../../api/generated/exports.dart';
import '../../shared/dates.dart';

/// "Kiedy mogę": the period the manager asked about (if any), whether I sent it, and whether the assistant reads.
final myAvailabilityProvider = FutureProvider.autoDispose.family<MyAvailabilityOut, String>(
  (ref, companyId) => ref.watch(apiProvider).availability.myAvailability(companyId: companyId),
);

/// One month of my calendar ("2026-12"): marked days, locked days, and the period asked about in it.
final myCalendarProvider = FutureProvider.autoDispose.family<MyCalendarOut, ({String companyId, String month})>((
  ref,
  key,
) {
  final bounds = monthBounds(key.month);
  return ref.watch(apiProvider).availability.myCalendar(companyId: key.companyId, start: bounds.start, end: bounds.end);
});
