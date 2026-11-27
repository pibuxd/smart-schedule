import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';

/// Asked at the top of the screens until the person has a name (an account starts without one).
class ProfileNameForm extends ConsumerStatefulWidget {
  const ProfileNameForm({super.key, required this.me});

  final MeOut me;

  @override
  ConsumerState<ProfileNameForm> createState() => _ProfileNameFormState();
}

class _ProfileNameFormState extends ConsumerState<ProfileNameForm> {
  late final _first = TextEditingController(text: widget.me.firstName);
  late final _last = TextEditingController(text: widget.me.lastName);
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _first.addListener(() => setState(() {}));
    _last.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _first.dispose();
    _last.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref
          .read(apiProvider)
          .auth
          .updateMe(
            body: MeIn(firstName: _first.text.trim(), lastName: _last.text.trim()),
          );
      ref.invalidate(meProvider);
    } catch (error) {
      if (mounted) setState(() => _error = errorMessage(error, networkProblem));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ready = _first.text.trim().isNotEmpty && _last.text.trim().isNotEmpty;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: AutofillGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              header: true,
              child: Text('Jak podpisać Cię w grafiku?', style: Theme.of(context).textTheme.titleMedium),
            ),
            const SizedBox(height: 12),
            NameFields(first: _first, last: _last),
            if (_error != null) ...[const SizedBox(height: 12), InlineError(_error!)],
            const SizedBox(height: 12),
            FilledButton(onPressed: _saving || !ready ? null : _save, child: const Text('Zapisz imię i nazwisko')),
          ],
        ),
      ),
    );
  }
}

/// "Imię" and "Nazwisko", with the limits the server keeps.
class NameFields extends StatelessWidget {
  const NameFields({super.key, required this.first, required this.last});

  final TextEditingController first;
  final TextEditingController last;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: first,
          maxLength: 80,
          textCapitalization: TextCapitalization.words,
          autofillHints: const [AutofillHints.givenName],
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(labelText: 'Imię', counterText: ''),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: last,
          maxLength: 120,
          textCapitalization: TextCapitalization.words,
          autofillHints: const [AutofillHints.familyName],
          decoration: const InputDecoration(labelText: 'Nazwisko', counterText: ''),
        ),
      ],
    );
  }
}
