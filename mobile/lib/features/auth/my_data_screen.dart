import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../shared/bank_account.dart';
import '../../shared/phone.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'profile_name_form.dart';
import 'sign_out_button.dart';

/// "Twoje dane", opened from the person icon at the top of every tab: name, the bank account number for pay
/// (optional), the company the screens show (when there are several) and "Wyloguj".
class MyDataScreen extends ConsumerWidget {
  const MyDataScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Twoje dane')),
      body: switch (session) {
        SessionReady(:final me, :final company) => ListView(
          padding: const EdgeInsets.fromLTRB(gutter, 8, gutter, 32),
          children: [
            _MyDataForm(me: me),
            if (me.companies.length > 1) ...[
              const SizedBox(height: 28),
              Semantics(header: true, child: Text('Firma', style: Theme.of(context).textTheme.titleMedium)),
              const SizedBox(height: 4),
              const Text('Ekrany pokazują tę firmę.', style: TextStyle(color: AppColors.inkMuted)),
              const SizedBox(height: 8),
              RadioGroup<String>(
                groupValue: company?.id,
                onChanged: (id) {
                  if (id != null) ref.read(companyChoiceProvider.notifier).choose(id);
                },
                child: Column(
                  children: [
                    for (final c in me.companies)
                      RadioListTile<String>.adaptive(value: c.id, title: Text(c.name), contentPadding: EdgeInsets.zero),
                  ],
                ),
              ),
            ],
            if (me.pendingInvitations > 0) ...[
              const SizedBox(height: 28),
              OutlinedButton(
                onPressed: () => context.push('/zaproszenia'),
                child: const Text('Zobacz nowe zaproszenie do pracy'),
              ),
            ],
            const SizedBox(height: 28),
            const SignOutButton(wide: true),
          ],
        ),
        _ => const Center(child: LoadingView('Otwieram Twoje dane…')),
      },
    );
  }
}

class _MyDataForm extends ConsumerStatefulWidget {
  const _MyDataForm({required this.me});

  final MeOut me;

  @override
  ConsumerState<_MyDataForm> createState() => _MyDataFormState();
}

class _MyDataFormState extends ConsumerState<_MyDataForm> {
  late final _first = TextEditingController(text: widget.me.firstName);
  late final _last = TextEditingController(text: widget.me.lastName);
  late final _account = TextEditingController(text: widget.me.bankAccount);
  bool _saving = false;
  bool _saved = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    for (final c in [_first, _last, _account]) {
      c.addListener(() => setState(() => _saved = false));
    }
  }

  @override
  void dispose() {
    _first.dispose();
    _last.dispose();
    _account.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _saving = true;
      _error = null;
    });
    final account = tidyBankAccount(_account.text);
    try {
      final me = await ref
          .read(apiProvider)
          .auth
          .updateMe(
            body: MeIn(
              firstName: _first.text.trim(),
              lastName: _last.text.trim(),
              // Sent only when changed: a manager may have written it, and an unchanged field must not overwrite theirs.
              bankAccount: account != widget.me.bankAccount ? account : null,
            ),
          );
      ref.invalidate(meProvider);
      if (mounted) {
        // The number as the server keeps it (spaces tidied); the change listener clears "Zapisane", so set it after.
        _account.text = me.bankAccount;
        setState(() => _saved = true);
      }
    } catch (error) {
      if (mounted) setState(() => _error = errorMessage(error, networkProblem));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ready = _first.text.trim().isNotEmpty && _last.text.trim().isNotEmpty;
    return AutofillGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          NameFields(first: _first, last: _last),
          const SizedBox(height: 12),
          TextField(
            controller: _account,
            maxLength: 100,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'Numer konta do wypłaty',
              helperText:
                  'Nieobowiązkowy. Widzą go tylko Twoi kierownicy (też w pliku z godzinami) i administrator '
                  'Grafikomatu.',
              counterText: '',
            ),
          ),
          const SizedBox(height: 12),
          Text(
            'Logujesz się numerem ${prettyPhone(widget.me.phone)}.',
            style: const TextStyle(fontSize: 14, color: AppColors.inkMuted),
          ),
          if (_error != null) ...[const SizedBox(height: 12), InlineError(_error!)],
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _saving || !ready ? null : _save,
            child: Text(_saving ? 'Zapisuję…' : (_saved ? 'Zapisane' : 'Zapisz dane')),
          ),
        ],
      ),
    );
  }
}
