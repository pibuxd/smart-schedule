import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/errors.dart';
import '../api/generated/exports.dart';
import 'prefs.dart';

/// Who is logged in: `GET /api/me`, or null when nobody is (401).
final FutureProvider<MeOut?> meProvider = FutureProvider<MeOut?>((ref) async {
  try {
    return await ref.watch(apiProvider).auth.me();
  } on DioException catch (error) {
    if (errorStatus(error) == 401) return null;
    rethrow;
  }
});

/// The company the screens show, remembered on this phone (a person may work for several).
class CompanyChoice extends Notifier<String?> {
  @override
  String? build() => ref.watch(prefsProvider).get(Prefs.companyKey);

  void choose(String companyId) {
    ref.read(prefsProvider).set(Prefs.companyKey, companyId);
    state = companyId;
  }
}

final companyChoiceProvider = NotifierProvider<CompanyChoice, String?>(CompanyChoice.new);

sealed class Session {
  const Session();
}

class SessionLoading extends Session {
  const SessionLoading();
}

class SessionLoggedOut extends Session {
  const SessionLoggedOut();
}

class SessionError extends Session {
  const SessionError(this.error);
  final Object error;
}

class SessionReady extends Session {
  const SessionReady(this.me, this.company);
  final MeOut me;

  /// The chosen company, else the first one; null for someone who has not accepted an invitation yet.
  final MyCompanyOut? company;

  bool get isManager => company != null && isManagerRole(company!.role);

  String get name => '${me.firstName} ${me.lastName}'.trim();
}

bool isManagerRole(MyCompanyOutRole role) => role == MyCompanyOutRole.owner || role == MyCompanyOutRole.manager;

/// The session as screens and the router see it. While `me` is being asked again (after login, logout, an accepted
/// invitation) the last answer stays on screen.
final sessionProvider = Provider<Session>((ref) {
  final me = ref.watch(meProvider);
  final chosen = ref.watch(companyChoiceProvider);
  if (me.hasValue) {
    final data = me.value;
    if (data == null) return const SessionLoggedOut();
    MyCompanyOut? company;
    for (final c in data.companies) {
      if (c.id == chosen) company = c;
    }
    company ??= data.companies.isEmpty ? null : data.companies.first;
    return SessionReady(data, company);
  }
  if (me.hasError) return SessionError(me.error!);
  return const SessionLoading();
});
