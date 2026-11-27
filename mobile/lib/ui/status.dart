import 'package:material_ui/material_ui.dart';

import 'theme.dart';

/// Loading state: plain words next to the spinner, never a spinner alone.
class LoadingView extends StatelessWidget {
  const LoadingView(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      label: text,
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator.adaptive(),
            const SizedBox(height: 12),
            Text(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.inkMuted),
            ),
          ],
        ),
      ),
    );
  }
}

/// Error state: what went wrong in plain words, and a way to try again.
class ErrorView extends StatelessWidget {
  const ErrorView(this.text, {super.key, this.onRetry});

  final String text;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.cannotSoft,
          border: Border.all(color: AppColors.cannot),
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(text, style: const TextStyle(color: AppColors.cannot)),
            if (onRetry != null) ...[
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onRetry, child: const Text('Spróbuj jeszcze raz')),
            ],
          ],
        ),
      ),
    );
  }
}

/// Empty state: says what will appear here and what to do now.
class EmptyView extends StatelessWidget {
  const EmptyView({super.key, required this.title, this.children = const []});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line, width: 2),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(header: true, child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
          for (final child in children) ...[const SizedBox(height: 8), child],
        ],
      ),
    );
  }
}

/// Short message under a form field or action.
class InlineError extends StatelessWidget {
  const InlineError(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(color: AppColors.cannotSoft, borderRadius: BorderRadius.circular(AppRadius.sm)),
        child: Text(text, style: const TextStyle(fontSize: 14, color: AppColors.cannot)),
      ),
    );
  }
}

/// A note in the accent colour at the top of a screen ("Sesja wygasła…").
class Notice extends StatelessWidget {
  const Notice(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(AppRadius.md)),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.w600)),
      ),
    );
  }
}
