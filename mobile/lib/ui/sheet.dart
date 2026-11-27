import 'package:material_ui/material_ui.dart';

import 'theme.dart';

/// A sheet that slides up from the bottom, like the website's `Sheet`: a title, one line saying what it is about, and
/// its content. It grows with the keyboard, and a swipe down or a tap outside closes it.
Future<void> showAppSheet(
  BuildContext context, {
  required String title,
  String? description,
  required WidgetBuilder builder,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    // Over the tab bar too, like sheets in other apps.
    useRootNavigator: true,
    useSafeArea: true,
    showDragHandle: true,
    backgroundColor: AppColors.surface,
    builder: (context) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(gutter, 0, gutter, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Semantics(header: true, child: Text(title, style: Theme.of(context).textTheme.titleLarge)),
            if (description != null) ...[
              const SizedBox(height: 4),
              Text(description, style: const TextStyle(color: AppColors.inkMuted)),
            ],
            const SizedBox(height: 16),
            builder(context),
          ],
        ),
      ),
    ),
  );
}

/// What a tapped notification is about, outlined like the website's focus ring.
class FocusOutline extends StatelessWidget {
  const FocusOutline({super.key, required this.focused, required this.child, this.radius = AppRadius.lg});

  final bool focused;
  final Widget child;
  final double radius;

  @override
  Widget build(BuildContext context) {
    if (!focused) return child;
    return Semantics(
      selected: true,
      child: Container(
        foregroundDecoration: BoxDecoration(
          border: Border.all(color: AppColors.accent, width: 3),
          borderRadius: BorderRadius.circular(radius),
        ),
        child: child,
      ),
    );
  }
}
