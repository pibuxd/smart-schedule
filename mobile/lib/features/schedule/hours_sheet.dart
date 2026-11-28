import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../shared/dates.dart';
import '../../ui/sheet.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'hours.dart';
import 'schedule_data.dart';

const _reasonMax = 300;

/// "Zgłoś inne godziny": the hours I really work on one of my published shifts, longer (overtime) or shorter (I feel
/// ill and leave early). The manager approves or rejects them; until then the schedule's hours count.
Future<void> showHoursSheet(BuildContext context, MyShiftOut shift, DateTime now) {
  return showAppSheet(
    context,
    title: 'Inne godziny tej zmiany',
    description:
        '${dayTitle(parseDate(shift.date))}, w grafiku ${shortTime(shift.startTime)}–${shortTime(shift.endTime)}, '
        '${shift.positionName}',
    builder: (context) => _ReportHours(shift: shift, now: now),
  );
}

class _ReportHours extends ConsumerStatefulWidget {
  const _ReportHours({required this.shift, required this.now});

  final MyShiftOut shift;
  final DateTime now;

  @override
  ConsumerState<_ReportHours> createState() => _ReportHoursState();
}

class _ReportHoursState extends ConsumerState<_ReportHours> {
  late final _start = TextEditingController(text: normalTime(countedStartTime(widget.shift)));
  late final _end = TextEditingController(text: normalTime(countedEndTime(widget.shift)));
  final _reason = TextEditingController();
  bool _sent = false;
  bool _busy = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _start.addListener(_changed);
    _end.addListener(_changed);
  }

  void _changed() => setState(() {});

  @override
  void dispose() {
    _start.dispose();
    _end.dispose();
    _reason.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_sent) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            liveRegion: true,
            child: const Text(
              'Wysłane. Kierownik zatwierdzi albo odrzuci te godziny, a Ty dostaniesz powiadomienie. Do tego czasu '
              'liczą się godziny z grafiku.',
            ),
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Gotowe')),
        ],
      );
    }

    final shift = widget.shift;
    final api = ref.read(apiProvider);
    final start = _start.text;
    final end = _end.text;
    final running = !countedStart(shift).isAfter(widget.now) && widget.now.isBefore(countedEnd(shift));
    final valid = isTime(start) && isTime(end);
    final planned = minutesBetween(shortTimeOf(shift.startTime), shortTimeOf(shift.endTime));
    final difference = valid ? minutesBetween(start, end) - planned : 0;
    final same =
        valid &&
        normalTime(start) == normalTime(countedStartTime(shift)) &&
        normalTime(end) == normalTime(countedEndTime(shift));
    final waiting = shift.report;
    final alreadyWaiting =
        valid &&
        waiting != null &&
        normalTime(start) == normalTime(waiting.startTime) &&
        normalTime(end) == normalTime(waiting.endTime);
    final worked = shift.worked;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (worked != null) ...[
          Text(
            'Liczą się ${shortTime(worked.startTime)}–${shortTime(worked.endTime)} '
            '(${worked.byManager ? 'od kierownika' : 'zatwierdzone'}).',
          ),
          const SizedBox(height: 12),
        ],
        if (waiting != null) ...[
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: AppColors.paper, borderRadius: BorderRadius.circular(AppRadius.md)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Czeka na kierownika: ${shortTime(waiting.startTime)}–${shortTime(waiting.endTime)} '
                  '(${differenceText(waiting.differenceMinutes)}). Nowe godziny zastąpią to zgłoszenie.',
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  style: OutlinedButton.styleFrom(minimumSize: const Size(64, touch)),
                  onPressed: _busy
                      ? null
                      : () => _run(() async {
                          await api.worktime.cancelMyHoursChange(changeId: waiting.id);
                          refreshSchedule(ref);
                          if (context.mounted) Navigator.of(context).pop();
                        }),
                  child: const Text('Wycofaj zgłoszenie'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
        ],
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TimeField(label: 'Od', controller: _start),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TimeField(label: 'Do', controller: _end),
            ),
          ],
        ),
        if (running) ...[
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, touch)),
              // The clock at the tap: the screen's time only moves at the edges of shifts.
              onPressed: () => _end.text = locationClockTime(ref.read(clockProvider)(), shift),
              child: const Text('Wychodzę teraz'),
            ),
          ),
        ],
        const SizedBox(height: 16),
        TextField(
          controller: _reason,
          maxLength: _reasonMax,
          textCapitalization: TextCapitalization.sentences,
          decoration: const InputDecoration(
            labelText: 'Powód (nie musisz pisać)',
            hintText: 'np. źle się czuję, dostawa',
            counterText: '',
          ),
        ),
        const SizedBox(height: 12),
        Semantics(
          liveRegion: true,
          child: Text(
            !valid
                ? 'Wpisz godziny od i do.'
                : same
                ? 'To te same godziny, które liczą się teraz.'
                : alreadyWaiting
                ? 'Takie zgłoszenie już czeka na kierownika.'
                : differenceSentence(difference),
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
        if (_error != null) ...[const SizedBox(height: 12), InlineError(errorMessage(_error, networkProblem))],
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy || !valid || same || alreadyWaiting
              ? null
              : () => _run(() async {
                  await api.worktime.reportMyHours(
                    body: ReportHoursIn(
                      assignmentId: shift.id,
                      startTime: normalTime(start),
                      endTime: normalTime(end),
                      reason: _reason.text.trim(),
                    ),
                  );
                  if (mounted) setState(() => _sent = true);
                  refreshSchedule(ref);
                }),
          child: Text(_busy ? 'Wysyłam…' : 'Wyślij kierownikowi'),
        ),
      ],
    );
  }
}

/// A time of day typed on the number keyboard ("1530" becomes "15:30"), or picked from the clock next to it.
class TimeField extends StatelessWidget {
  const TimeField({super.key, required this.label, required this.controller});

  final String label;
  final TextEditingController controller;

  Future<void> _pick(BuildContext context) async {
    final now = isTime(controller.text) ? normalTime(controller.text).split(':').map(int.parse).toList() : [8, 0];
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: now[0], minute: now[1]),
      helpText: label,
      builder: (context, child) =>
          MediaQuery(data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true), child: child!),
    );
    if (picked != null) {
      controller.text = '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    }
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: TextInputType.number,
      inputFormatters: [TimeTextFormatter()],
      decoration: InputDecoration(
        labelText: label,
        hintText: 'GG:MM',
        suffixIcon: IconButton(
          tooltip: 'Wybierz godzinę: $label',
          icon: const Icon(Icons.schedule),
          onPressed: () => _pick(context),
        ),
      ),
    );
  }
}

/// Keeps only digits and puts the colon in: "6" "60" "600" -> "6:00", "1" "15" "153" "1530" -> "15:30".
class TimeTextFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    final text = formatTimeDigits(newValue.text);
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }
}

String formatTimeDigits(String input) {
  var digits = input.replaceAll(RegExp(r'\D'), '');
  if (digits.length > 4) digits = digits.substring(0, 4);
  if (digits.isEmpty) return '';
  // An hour from 3 on is one digit ("6:00"); "2" followed by 4–9 is too ("2:45").
  final first = int.parse(digits[0]);
  final oneDigitHour = first > 2 || (first == 2 && digits.length > 1 && int.parse(digits[1]) > 3);
  final hourLength = oneDigitHour ? 1 : 2;
  if (digits.length <= hourLength) return digits;
  final minutesEnd = digits.length < hourLength + 2 ? digits.length : hourLength + 2;
  return '${digits.substring(0, hourLength)}:${digits.substring(hourLength, minutesEnd)}';
}
