import 'package:material_ui/material_ui.dart';

import '../../shared/dates.dart';
import '../../ui/theme.dart';
import 'marks.dart';
import 'state_look.dart';

/// The month as a squared-paper grid (the website's `AvailabilityCalendar`). A tap marks one day; moving the finger
/// scrolls the screen, so marking never fights scrolling. A screen reader reads each day with its state.
class AvailabilityCalendar extends StatelessWidget {
  const AvailabilityCalendar({
    super.key,
    required this.start,
    required this.end,
    required this.marks,
    required this.disabled,
    required this.locked,
    required this.onTapDay,
  });

  final String start;
  final String end;
  final Marks marks;
  final bool disabled;

  /// Days that cannot be changed (past days, days with an arranged schedule): dimmed, taps do nothing.
  final Set<String> locked;
  final ValueChanged<String> onTapDay;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Kalendarz dni',
      container: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ExcludeSemantics(
            child: Row(
              children: [
                for (final (i, name) in weekdayHeaders.indexed)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Text(
                        name,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: i > 4 ? AppColors.ink : AppColors.inkMuted,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          for (final week in calendarWeeks(start, end))
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (final (i, date) in week.indexed) ...[
                      if (i > 0) const SizedBox(width: 3),
                      Expanded(
                        child: date == null
                            ? const SizedBox.shrink()
                            : _DayCell(
                                key: ValueKey(date),
                                date: date,
                                mark: markOf(marks, date),
                                disabled: disabled || locked.contains(date),
                                onTap: () => onTapDay(date),
                              ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _DayCell extends StatelessWidget {
  const _DayCell({super.key, required this.date, required this.mark, required this.disabled, required this.onTap});

  final String date;
  final Mark mark;
  final bool disabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final day = parseDate(date);
    final hours = cellHours(mark);
    final label = '${dayTitle(day)}: ${describeMark(mark)}${disabled ? ', nie da się zmienić' : ''}';
    return Semantics(
      button: true,
      enabled: !disabled,
      label: label,
      excludeSemantics: true,
      onTap: disabled ? null : onTap,
      child: Opacity(
        opacity: disabled ? 0.45 : 1,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: disabled ? null : onTap,
          child: StateBox(
            state: mark.state,
            radius: AppRadius.sm,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 64),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '${day.day}',
                      style: const TextStyle(
                        fontSize: 16,
                        height: 1.2,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                        fontFeatures: [FontFeature.tabularFigures()],
                      ),
                    ),
                    StateIcon(state: mark.state, size: hours == null ? 20 : 16),
                    if (hours != null)
                      Text(
                        hours,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 12,
                          height: 1,
                          fontWeight: FontWeight.w600,
                          color: StateLook.of(mark.state).ink,
                          fontFeatures: const [FontFeature.tabularFigures()],
                        ),
                      )
                    else
                      const SizedBox(height: 2),
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
