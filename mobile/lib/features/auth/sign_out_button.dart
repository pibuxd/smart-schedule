import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../session/sign_out.dart';
import '../../ui/theme.dart';

/// "Wyloguj". When the server does not confirm (no internet), the session goes on: the person stays logged in, and
/// a message at the bottom says so and offers to try again.
class SignOutButton extends ConsumerStatefulWidget {
  const SignOutButton({super.key, this.wide = false});

  /// A full-width button (in "Twoje dane") instead of a link in the top bar.
  final bool wide;

  @override
  ConsumerState<SignOutButton> createState() => _SignOutButtonState();
}

class _SignOutButtonState extends ConsumerState<SignOutButton> {
  bool _pending = false;

  Future<void> _run() async {
    if (_pending) return;
    setState(() => _pending = true);
    final messenger = ScaffoldMessenger.of(context);
    final done = await signOut(ref);
    if (mounted) setState(() => _pending = false);
    if (!done) {
      messenger.showSnackBar(
        SnackBar(
          content: const Text('Nie udało się wylogować. Sesja trwa dalej. Sprawdź internet.'),
          backgroundColor: AppColors.cannot,
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 8),
          action: SnackBarAction(label: 'Wyloguj jeszcze raz', textColor: AppColors.accentInk, onPressed: _run),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.wide) {
      return OutlinedButton(onPressed: _pending ? null : _run, child: const Text('Wyloguj'));
    }
    return TextButton(onPressed: _pending ? null : _run, child: const Text('Wyloguj'));
  }
}
