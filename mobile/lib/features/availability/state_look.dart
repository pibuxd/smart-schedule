import 'package:material_ui/material_ui.dart';

import '../../ui/theme.dart';
import 'marks.dart';

/// How each availability state looks: colour, border and pattern (the website's `.avail-*` classes). States always
/// differ by colour, icon and pattern, never by colour alone.
class StateLook {
  const StateLook._(this.ink, this.border, this.fill, {this.hatched = false});

  final Color ink;
  final Color border;
  final Color fill;

  /// "Nie mogę" is crossed with diagonal lines.
  final bool hatched;

  static StateLook of(AvailabilityState state) => switch (state) {
    AvailabilityState.cannot => const StateLook._(
      AppColors.cannot,
      AppColors.cannot,
      AppColors.cannotSoft,
      hatched: true,
    ),
    AvailabilityState.neutral => const StateLook._(AppColors.can, AppColors.canLine, AppColors.canSoft),
    AvailabilityState.prefer => const StateLook._(AppColors.prefer, AppColors.prefer, AppColors.preferFill),
  };
}

/// A box in a state's colours and pattern, e.g. a calendar day or the small square in a state button.
class StateBox extends StatelessWidget {
  const StateBox({super.key, required this.state, required this.child, this.radius = AppRadius.sm, this.padding});

  final AvailabilityState state;
  final Widget child;
  final double radius;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final look = StateLook.of(state);
    final shape = BorderRadius.circular(radius);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: look.fill,
        borderRadius: shape,
        border: Border.all(color: look.border, width: 2),
      ),
      child: ClipRRect(
        borderRadius: shape,
        child: CustomPaint(
          painter: look.hatched ? const _Hatch(Color(0x29B3261E)) : null,
          child: Padding(padding: padding ?? EdgeInsets.zero, child: child),
        ),
      ),
    );
  }
}

/// Lines both ways at 45°, 2 px every 8 px, like the website's `repeating-linear-gradient`.
class _Hatch extends CustomPainter {
  const _Hatch(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 2;
    final reach = size.width + size.height;
    for (var x = -size.height; x < reach; x += 8 * 1.4142) {
      canvas.drawLine(Offset(x, 0), Offset(x + size.height, size.height), paint);
      canvas.drawLine(Offset(x, size.height), Offset(x + size.height, 0), paint);
    }
  }

  @override
  bool shouldRepaint(_Hatch old) => old.color != color;
}

/// The sign of each state: a cross, a thin tick ("mogę"), a double tick ("chętnie"). Drawn, never an emoji.
class StateIcon extends StatelessWidget {
  const StateIcon({super.key, required this.state, this.size = 20, this.color});

  final AvailabilityState state;
  final double size;

  /// The state's own colour when left out.
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: CustomPaint(size: Size.square(size), painter: _StateIconPainter(state, color ?? StateLook.of(state).ink)),
    );
  }
}

class _StateIconPainter extends CustomPainter {
  const _StateIconPainter(this.state, this.color);

  final AvailabilityState state;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    // The website's 24 × 24 drawing, scaled.
    canvas.scale(size.width / 24);
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    switch (state) {
      case AvailabilityState.cannot:
        paint.strokeWidth = 3;
        canvas.drawLine(const Offset(6, 6), const Offset(18, 18), paint);
        canvas.drawLine(const Offset(18, 6), const Offset(6, 18), paint);
      case AvailabilityState.neutral:
        paint.strokeWidth = 2;
        canvas.drawPath(
          Path()
            ..moveTo(5.5, 12.5)
            ..lineTo(10, 17)
            ..lineTo(18.5, 8),
          paint,
        );
      case AvailabilityState.prefer:
        paint.strokeWidth = 3;
        canvas.drawPath(
          Path()
            ..moveTo(2, 13)
            ..lineTo(6, 17)
            ..lineTo(14.5, 7.5),
          paint,
        );
        canvas.drawPath(
          Path()
            ..moveTo(10.5, 15.5)
            ..lineTo(12, 17)
            ..lineTo(21.5, 7.5),
          paint,
        );
    }
  }

  @override
  bool shouldRepaint(_StateIconPainter old) => old.state != state || old.color != color;
}

/// Three big buttons, one per state; the chosen one is outlined in the accent colour (the website's `StatePicker`).
/// [compact] puts the icon beside the word, for the bar at the bottom of a short screen.
class StateButtons extends StatelessWidget {
  const StateButtons({super.key, required this.value, required this.onChanged, this.compact = false});

  final AvailabilityState? value;
  final ValueChanged<AvailabilityState> onChanged;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (final (i, state) in AvailabilityState.values.indexed) ...[
          if (i > 0) const SizedBox(width: 6),
          Expanded(
            child: ChoiceBox(
              chosen: value == state,
              onTap: () => onChanged(state),
              minHeight: compact ? touch : 64,
              child: Flex(
                direction: compact ? Axis.horizontal : Axis.vertical,
                mainAxisAlignment: MainAxisAlignment.center,
                mainAxisSize: MainAxisSize.min,
                children: [
                  StateBox(
                    state: state,
                    child: SizedBox.square(
                      dimension: 24,
                      child: Center(child: StateIcon(state: state, size: 16)),
                    ),
                  ),
                  SizedBox(width: compact ? 6 : 0, height: compact ? 0 : 4),
                  Flexible(
                    child: Text(
                      state.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

/// A bordered button that is either chosen (accent outline and tint) or not, like the website's `aria-pressed`
/// buttons and radio labels.
class ChoiceBox extends StatelessWidget {
  const ChoiceBox({
    super.key,
    required this.chosen,
    required this.onTap,
    required this.child,
    this.minHeight = touch,
    this.padding = const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
    this.radio = false,
    this.alignment = Alignment.center,
  });

  final bool chosen;
  final VoidCallback onTap;
  final Widget child;
  final double minHeight;
  final EdgeInsetsGeometry padding;

  /// One of a group, of which exactly one is chosen (read out as a radio button).
  final bool radio;
  final AlignmentGeometry alignment;

  @override
  Widget build(BuildContext context) {
    final shape = BorderRadius.circular(AppRadius.md);
    return Semantics(
      button: !radio,
      selected: chosen,
      checked: radio ? chosen : null,
      inMutuallyExclusiveGroup: radio ? true : null,
      child: Material(
        color: chosen ? AppColors.accentSoft : AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: shape,
          side: BorderSide(color: chosen ? AppColors.accent : AppColors.line, width: 2),
        ),
        child: InkWell(
          borderRadius: shape,
          onTap: onTap,
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: minHeight),
            child: Padding(
              padding: padding,
              child: Align(alignment: alignment, child: child),
            ),
          ),
        ),
      ),
    );
  }
}
