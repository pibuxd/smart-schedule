import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../session/session.dart';
import '../../shared/phone.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import '../../ui/wordmark.dart';
import 'code_input.dart';
import 'phone_input.dart';

/// Logging in: the phone number, then the 6-digit code from the SMS. A new company is registered on the website.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  RequestCodeOut? _sent;
  late final bool _sessionEnded;

  @override
  void initState() {
    super.initState();
    _sessionEnded = ref.read(sessionEndedProvider);
    // Said once: cleared after this first frame (providers may not change while the screen is being built).
    if (_sessionEnded) {
      WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(sessionEndedProvider.notifier).clear());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(gutter, 24, gutter, 32),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight - 56),
              child: IntrinsicHeight(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Wordmark(),
                    const SizedBox(height: 32),
                    Expanded(
                      child: _sent == null
                          ? _PhoneStep(sessionEnded: _sessionEnded, onSent: (sent) => setState(() => _sent = sent))
                          : _CodeStep(
                              key: ValueKey(_sent),
                              sent: _sent!,
                              onResent: (sent) => setState(() => _sent = sent),
                              onChangePhone: () => setState(() => _sent = null),
                            ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PhoneStep extends ConsumerStatefulWidget {
  const _PhoneStep({required this.sessionEnded, required this.onSent});

  final bool sessionEnded;
  final ValueChanged<RequestCodeOut> onSent;

  @override
  ConsumerState<_PhoneStep> createState() => _PhoneStepState();
}

class _PhoneStepState extends ConsumerState<_PhoneStep> {
  final _phone = TextEditingController();
  final _focus = FocusNode();
  String _region = poland.region;
  String? _fieldError;
  String? _requestError;
  bool _pending = false;

  @override
  void dispose() {
    _phone.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_pending) return;
    final problem = phoneProblem(_region, _phone.text);
    setState(() {
      _fieldError = problem;
      _requestError = null;
    });
    if (problem != null) return;
    setState(() => _pending = true);
    try {
      final sent = await ref
          .read(apiProvider)
          .auth
          .requestCode(
            body: RequestCodeIn(phone: phoneToSend(_region, _phone.text), purpose: RequestCodeInPurpose.login),
          );
      if (mounted) widget.onSent(sent);
    } catch (error) {
      if (mounted) setState(() => _requestError = errorMessage(error, networkProblem));
    } finally {
      if (mounted) setState(() => _pending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AutofillGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(header: true, child: Text('Zaloguj się', style: theme.textTheme.headlineSmall)),
          const SizedBox(height: 8),
          const Text('Wpisz swój numer telefonu. Wyślemy Ci SMS z kodem.', style: TextStyle(color: AppColors.inkMuted)),
          if (widget.sessionEnded) ...[
            const SizedBox(height: 8),
            const Notice('Sesja wygasła. Zaloguj się jeszcze raz. To, co już zapisane, zostało.'),
          ],
          const SizedBox(height: 20),
          const Text('Numer telefonu', style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          PhoneInput(
            region: _region,
            onRegionChanged: (region) => setState(() => _region = region),
            controller: _phone,
            focusNode: _focus,
            error: _fieldError,
            enabled: !_pending,
            onSubmitted: _submit,
          ),
          if (_requestError != null) ...[const SizedBox(height: 16), InlineError(_requestError!)],
          const Spacer(),
          const SizedBox(height: 24),
          FilledButton(onPressed: _pending ? null : _submit, child: Text(_pending ? 'Wysyłam kod…' : 'Wyślij kod SMS')),
        ],
      ),
    );
  }
}

class _CodeStep extends ConsumerStatefulWidget {
  const _CodeStep({super.key, required this.sent, required this.onResent, required this.onChangePhone});

  final RequestCodeOut sent;
  final ValueChanged<RequestCodeOut> onResent;
  final VoidCallback onChangePhone;

  @override
  ConsumerState<_CodeStep> createState() => _CodeStepState();
}

class _CodeStepState extends ConsumerState<_CodeStep> {
  final _code = TextEditingController();
  Timer? _timer;
  late int _left = widget.sent.resendAfterS;
  bool _checking = false;
  bool _resending = false;
  String? _verifyError;
  String? _resendError;

  @override
  void initState() {
    super.initState();
    _code.addListener(_typed);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_left > 0) setState(() => _left -= 1);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    super.dispose();
  }

  void _typed() {
    // A new digit starts a new try: the old "wrong code" message would only confuse.
    if (_verifyError != null && _code.text.length < 6) setState(() => _verifyError = null);
    if (_code.text.length == 6 && !_checking) _verify(_code.text);
  }

  Future<void> _verify(String code) async {
    setState(() {
      _checking = true;
      _verifyError = null;
    });
    try {
      await ref
          .read(apiProvider)
          .auth
          .verifyCode(
            body: VerifyCodeIn(phone: widget.sent.phone, code: code),
          );
      // The server handed over the session key; who is logged in decides where the router goes.
      ref.invalidate(meProvider);
    } catch (error) {
      if (mounted) setState(() => _verifyError = errorMessage(error, networkProblem));
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _resend() async {
    setState(() {
      _resending = true;
      _resendError = null;
    });
    try {
      final sent = await ref
          .read(apiProvider)
          .auth
          .requestCode(
            body: RequestCodeIn(phone: widget.sent.phone, purpose: RequestCodeInPurpose.login),
          );
      if (mounted) widget.onResent(sent);
    } catch (error) {
      if (mounted) setState(() => _resendError = errorMessage(error, networkProblem));
    } finally {
      if (mounted) setState(() => _resending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final minutes = _left ~/ 60;
    final seconds = (_left % 60).toString().padLeft(2, '0');
    final valid = (widget.sent.expiresInS / 60).round().clamp(1, 999);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(header: true, child: Text('Wpisz kod z SMS-a', style: theme.textTheme.headlineSmall)),
        const SizedBox(height: 8),
        Text.rich(
          TextSpan(
            style: const TextStyle(color: AppColors.inkMuted),
            children: [
              const TextSpan(text: 'Wysłaliśmy go na numer '),
              TextSpan(
                text: prettyPhone(widget.sent.phone),
                style: const TextStyle(color: AppColors.ink, fontWeight: FontWeight.w700),
              ),
              TextSpan(text: '. Kod jest ważny $valid min.'),
            ],
          ),
        ),
        const SizedBox(height: 20),
        CodeInput(controller: _code, enabled: !_checking, invalid: _verifyError != null),
        const SizedBox(height: 16),
        if (_checking)
          const Text('Sprawdzam kod…', style: TextStyle(color: AppColors.inkMuted))
        else if (_verifyError != null)
          InlineError(_verifyError!),
        if (_resendError != null) ...[const SizedBox(height: 8), InlineError(_resendError!)],
        const Spacer(),
        const SizedBox(height: 24),
        if (_left > 0)
          Semantics(
            liveRegion: false,
            child: Text(
              'Nowy kod możesz dostać za $minutes:$seconds.',
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          )
        else
          OutlinedButton(onPressed: _resending ? null : _resend, child: const Text('Wyślij kod jeszcze raz')),
        const SizedBox(height: 4),
        TextButton(onPressed: widget.onChangePhone, child: const Text('Zmień numer telefonu')),
      ],
    );
  }
}
