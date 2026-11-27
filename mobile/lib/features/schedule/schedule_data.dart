import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/client.dart';
import '../../api/generated/exports.dart';

/// The time the screens go by. Tests set it; the app reads the phone's clock.
final clockProvider = Provider<DateTime Function()>((ref) => DateTime.now);

/// "Mój grafik": my published shifts from today on, the last two weeks, and my hours and pay per month.
final myScheduleProvider = FutureProvider.autoDispose.family<MyScheduleOut, String>(
  (ref, companyId) => ref.watch(apiProvider).scheduling.mySchedule(companyId: companyId),
);

/// "Zmiany do wzięcia": shifts colleagues give away that I could take.
final availableOffersProvider = FutureProvider.autoDispose.family<List<AvailableOfferOut>, String>(
  (ref, companyId) => ref.watch(apiProvider).marketplace.availableOffers(companyId: companyId),
);

/// After giving away, taking or reporting hours, both lists are asked again (one change touches both).
void refreshSchedule(WidgetRef ref) {
  ref.invalidate(myScheduleProvider);
  ref.invalidate(availableOffersProvider);
}

/// The hours that count: approved other hours, else the schedule's.
DateTime countedStart(MyShiftOut shift) => shift.worked?.startAt ?? shift.startAt;
DateTime countedEnd(MyShiftOut shift) => shift.worked?.endAt ?? shift.endAt;
String countedStartTime(MyShiftOut shift) => shift.worked?.startTime ?? shift.startTime;
String countedEndTime(MyShiftOut shift) => shift.worked?.endTime ?? shift.endTime;
