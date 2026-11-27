import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/client.dart';
import '../../api/generated/exports.dart';
import '../availability/availability_data.dart';
import '../schedule/schedule_data.dart';

/// One conversation of a person: the period the manager asked for ([periodId]), or before that a month ([month], its
/// first day, "2026-12-01"). [editable] = new messages and changes are still taken.
class ChatScope {
  const ChatScope({this.periodId, this.month, required this.editable});

  final String? periodId;
  final String? month;
  final bool editable;

  /// Drafts and the chat itself are kept per conversation.
  String get key => '${periodId ?? month}:$editable';

  @override
  bool operator ==(Object other) =>
      other is ChatScope && other.periodId == periodId && other.month == month && other.editable == editable;

  @override
  int get hashCode => Object.hash(periodId, month, editable);
}

typedef RequestsKey = ({String companyId, String? periodId, String? month});

RequestsKey requestsKey(String companyId, ChatScope scope) =>
    (companyId: companyId, periodId: scope.periodId, month: scope.periodId == null ? scope.month : null);

/// How long a fresh message is shown as "being read" before the app stops asking the server.
const readingTime = Duration(seconds: 60);

/// My messages of one conversation, oldest first. While the assistant is still reading a fresh one, the list is
/// asked again every 2 seconds (as long as a screen shows it).
final myRequestsProvider = FutureProvider.autoDispose.family<List<MyRequestOut>, RequestsKey>((ref, key) async {
  final list = await ref
      .watch(apiProvider)
      .availability
      .myRequests(companyId: key.companyId, periodId: key.periodId, month: key.month);
  final now = ref.read(clockProvider)();
  final reading = list.any(
    (request) => request.status == MyRequestOutStatus.new2 && now.difference(request.createdAt) < readingTime,
  );
  if (reading) {
    final timer = Timer(const Duration(seconds: 2), ref.invalidateSelf);
    ref.onDispose(timer.cancel);
  }
  return list;
});

/// After a change in one conversation: its list, and everything a request can change (the calendar after "Zaznacz",
/// "Mój grafik" after a report of other hours).
void refreshAfterRequest(WidgetRef ref, {bool calendar = false, bool schedule = false}) {
  ref.invalidate(myRequestsProvider);
  if (calendar) {
    ref.invalidate(myCalendarProvider);
    ref.invalidate(myAvailabilityProvider);
  }
  if (schedule) refreshSchedule(ref);
}
