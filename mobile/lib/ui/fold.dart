import 'package:material_ui/material_ui.dart';

import 'theme.dart';

/// A section folded under its heading, like the website's `<Section collapsible>`: the heading with a few words of
/// status, a chevron that turns, and the content (with its one-line description on top) only while open. For lists a
/// person rarely needs, so they do not push the screen's main content down.
class Fold extends StatefulWidget {
  const Fold({
    super.key,
    required this.title,
    required this.child,
    this.status,
    this.description,
    this.initiallyOpen = false,
  });

  final String title;
  final Widget child;

  /// A few words at the end of the folded heading ("2 zmiany · czeka na kierownika: 1").
  final InlineSpan? status;
  final String? description;

  /// Open at first, e.g. when a tapped notification is about something inside.
  final bool initiallyOpen;

  @override
  State<Fold> createState() => _FoldState();
}

class _FoldState extends State<Fold> {
  late bool _open = widget.initiallyOpen;

  @override
  Widget build(BuildContext context) {
    final heading = Theme.of(context).textTheme.titleMedium;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          button: true,
          expanded: _open,
          header: true,
          child: InkWell(
            borderRadius: BorderRadius.circular(AppRadius.sm),
            onTap: () => setState(() => _open = !_open),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: touch),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    Expanded(
                      child: Text.rich(
                        TextSpan(
                          children: [
                            TextSpan(text: widget.title, style: heading),
                            if (widget.status != null) ...[
                              const TextSpan(text: '  '),
                              TextSpan(style: const TextStyle(fontSize: 14), children: [widget.status!]),
                            ],
                          ],
                        ),
                      ),
                    ),
                    AnimatedRotation(
                      turns: _open ? 0.5 : 0,
                      duration: const Duration(milliseconds: 150),
                      child: const Icon(Icons.expand_more, color: AppColors.inkMuted),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 150),
          alignment: Alignment.topCenter,
          child: _open
              ? Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (widget.description != null) ...[
                        Text(widget.description!, style: Theme.of(context).textTheme.bodySmall),
                        const SizedBox(height: 8),
                      ],
                      widget.child,
                    ],
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}
