import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../shared/phone.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'profile_name_form.dart';
import 'sign_out_button.dart';

final myInvitationsProvider = FutureProvider.autoDispose<List<MyInvitationOut>>(
  (ref) => ref.watch(apiProvider).tenancy.myInvitations(),
);

String _roleWord(MyInvitationOutRole role) => role == MyInvitationOutRole.manager ? 'kierownik' : 'pracownik';

/// Invitations waiting for this phone number. Also the screen of a person with no company yet, so it has its own
/// "Wyloguj" (someone who logged in with the wrong number must be able to try another one).
class InvitationsScreen extends ConsumerWidget {
  const InvitationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    if (session is! SessionReady) return const Scaffold(body: Center(child: LoadingView('Otwieram Grafikomat…')));
    final me = session.me;
    final invitations = ref.watch(myInvitationsProvider);
    final phone = prettyPhone(me.phone);
    return Scaffold(
      appBar: AppBar(title: const Text('Zaproszenia do pracy'), actions: const [SignOutButton()]),
      body: RefreshIndicator.adaptive(
        onRefresh: () => ref.refresh(myInvitationsProvider.future),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(gutter, 8, gutter, 32),
          children: [
            if (session.name.isEmpty && me.companies.isNotEmpty) ...[
              ProfileNameForm(me: me),
              const SizedBox(height: 16),
            ],
            switch (invitations) {
              AsyncValue(:final value?) when value.isEmpty => EmptyView(
                title: 'Nie masz żadnych zaproszeń',
                children: [
                  Text(
                    'Gdy kierownik zaprosi Cię na numer $phone, zaproszenie pojawi się tutaj.',
                    style: const TextStyle(color: AppColors.inkMuted),
                  ),
                  if (me.companies.isNotEmpty)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(onPressed: () => context.go('/grafik'), child: const Text('Wróć do grafiku')),
                    ),
                ],
              ),
              AsyncValue(:final value?) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final invitation in value) ...[
                    _InvitationCard(invitation: invitation),
                    const SizedBox(height: 16),
                  ],
                  // The app has no address bar: someone who already works somewhere can decide later.
                  if (me.companies.isNotEmpty)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(onPressed: () => context.go('/grafik'), child: const Text('Wróć do grafiku')),
                    ),
                ],
              ),
              AsyncValue(:final error?) => ErrorView(
                errorMessage(error, 'Nie udało się wczytać zaproszeń. Sprawdź internet i spróbuj jeszcze raz.'),
                onRetry: () => ref.invalidate(myInvitationsProvider),
              ),
              _ => const LoadingView('Sprawdzam zaproszenia…'),
            },
          ],
        ),
      ),
    );
  }
}

class _InvitationCard extends ConsumerStatefulWidget {
  const _InvitationCard({required this.invitation});

  final MyInvitationOut invitation;

  @override
  ConsumerState<_InvitationCard> createState() => _InvitationCardState();
}

class _InvitationCardState extends ConsumerState<_InvitationCard> {
  bool _confirmDecline = false;
  bool _busy = false;
  String? _error;

  Future<void> _answer({required bool accept}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final tenancy = ref.read(apiProvider).tenancy;
    try {
      if (accept) {
        await tenancy.acceptInvitation(invitationId: widget.invitation.id);
      } else {
        await tenancy.declineInvitation(invitationId: widget.invitation.id);
      }
      ref.invalidate(myInvitationsProvider);
      ref.invalidate(meProvider);
      if (accept && mounted) {
        await ref.read(meProvider.future);
        if (mounted) context.go('/');
      }
    } catch (error) {
      if (mounted) setState(() => _error = errorMessage(error, networkProblem));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final invitation = widget.invitation;
    final rows = <(String, String)>[
      ('Lokal', invitation.locationName),
      if (invitation.locationAddress.isNotEmpty) ('Adres', invitation.locationAddress),
      if (invitation.invitedByName.isNotEmpty) ('Zaprasza', invitation.invitedByName),
      ('Jako', _roleWord(invitation.role)),
    ];
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(header: true, child: Text(invitation.companyName, style: Theme.of(context).textTheme.titleMedium)),
          const SizedBox(height: 12),
          for (final (label, value) in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 88,
                    child: Text(label, style: const TextStyle(color: AppColors.inkMuted)),
                  ),
                  Expanded(
                    child: Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 10),
          if (_confirmDecline)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(color: AppColors.cannotSoft, borderRadius: BorderRadius.circular(AppRadius.md)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Na pewno odrzucić? Jeśli zmienisz zdanie, kierownik będzie musiał zaprosić Cię jeszcze raz.',
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.cannot,
                      side: const BorderSide(color: AppColors.cannot, width: 2),
                    ),
                    onPressed: _busy ? null : () => _answer(accept: false),
                    child: const Text('Tak, odrzucam'),
                  ),
                  const SizedBox(height: 8),
                  OutlinedButton(
                    onPressed: _busy ? null : () => setState(() => _confirmDecline = false),
                    child: const Text('Wróć'),
                  ),
                ],
              ),
            )
          else ...[
            const Text(
              'Gdy przyjmiesz zaproszenie, zobaczysz swój grafik i zaznaczysz, kiedy możesz pracować.',
              style: TextStyle(color: AppColors.inkMuted),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _busy ? null : () => _answer(accept: true),
              child: Text(_busy ? 'Przyjmuję…' : 'Przyjmij zaproszenie'),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: _busy ? null : () => setState(() => _confirmDecline = true),
              child: const Text('Odrzucam'),
            ),
          ],
          if (_error != null) ...[const SizedBox(height: 12), InlineError(_error!)],
        ],
      ),
    );
  }
}
