import 'package:material_ui/material_ui.dart';

import '../../shared/dates.dart';
import '../../ui/sheet.dart';
import '../../ui/theme.dart';
import 'marks.dart';
import 'state_look.dart';

/// Every half hour; "00:00" as an end means midnight.
final _times = [for (var i = 0; i < 48; i++) '${(i ~/ 2).toString().padLeft(2, '0')}:${i.isOdd ? '30' : '00'}'];

/// The half hours, plus a saved time between them ("09:15" from "nie mogę 9:15–11:45"), so the list shows it.
List<String> _timesWith(String value) => _times.contains(value) ? _times : ([..._times, value]..sort());

String _timeLabel(String value, {required bool asEnd}) =>
    asEnd && value == '00:00' ? '0:00 (północ)' : shortTime(value);

String _endWords(String value) => value == '00:00' ? '24:00' : shortTime(value);

/// One day in detail (the website's `DayHoursSheet`): the state and, if needed, the hours. "Chętnie"/"Mogę" with hours
/// = "I can only then"; "Nie mogę" is always the whole day (Piotr, 25.11.2026), so hours someone cannot work are
/// marked as the hours they can. Gives back the new mark, or null when closed without saving.
Future<Mark?> showDayHoursSheet(BuildContext context, {required String date, required Mark mark}) {
  return showAppSheet<Mark>(
    context,
    title: dayTitle(parseDate(date)),
    builder: (context) => DayHours(mark: mark, onSave: (mark) => Navigator.of(context).pop(mark)),
  );
}

class DayHours extends StatefulWidget {
  const DayHours({super.key, required this.mark, required this.onSave});

  final Mark mark;
  final ValueChanged<Mark> onSave;

  @override
  State<DayHours> createState() => _DayHoursState();
}

class _DayHoursState extends State<DayHours> {
  late AvailabilityState _state = widget.mark.state;
  late bool _limited = hasHours(widget.mark);
  // A saved window open at one end ("do 15:00") starts or ends at midnight; a day without hours suggests 14–22.
  late String _from = widget.mark.from ?? (hasHours(widget.mark) ? '00:00' : '14:00');
  late String _to = widget.mark.to ?? (hasHours(widget.mark) ? '00:00' : '22:00');
  late bool _second = hasSecondWindow(widget.mark);
  late String _from2 = widget.mark.from2 ?? '18:00';
  late String _to2 = widget.mark.to2 ?? '22:00';
  late bool _oneShift = widget.mark.oneShift;

  @override
  Widget build(BuildContext context) {
    final wholeDay = _state == AvailabilityState.cannot;
    final hours = _limited && !wholeDay;
    final two = hours && _second;
    final draft = hours
        ? Mark(
            _state,
            from: _from,
            to: _to,
            from2: two ? _from2 : null,
            to2: two ? _to2 : null,
            oneShift: two && _oneShift,
          )
        : Mark(_state);
    final empty = hours && (_from == _to || (two && _from2 == _to2));
    // "Od 20:00 do 16:00" is more likely swapped fields than a 20-hour night, so it needs a second look.
    final longNight = hours && !empty && overnight(draft) && spanHours(_from, _to) > 12;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          label: 'Stan dnia',
          container: true,
          child: StateButtons(value: _state, onChanged: (state) => setState(() => _state = state)),
        ),
        const SizedBox(height: 20),
        if (wholeDay)
          const Text(
            '„Nie mogę” jest na cały dzień. Możesz w części dnia? Wybierz „Mogę” i godziny, w których możesz.',
            style: TextStyle(fontSize: 14, color: AppColors.inkMuted),
          )
        else ...[
          const Text('Godziny', style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          _Option(chosen: !_limited, title: 'Cały dzień', onTap: () => setState(() => _limited = false)),
          const SizedBox(height: 8),
          _Option(
            chosen: _limited,
            title: 'Mogę tylko w tych godzinach',
            detail: 'Poza tymi godzinami tego dnia nie dostaniesz zmiany.',
            onTap: () => setState(() => _limited = true),
          ),
        ],
        if (hours) ...[
          const SizedBox(height: 16),
          _Window(
            from: _from,
            to: _to,
            onFrom: (value) => setState(() => _from = value),
            onTo: (value) => setState(() => _to = value),
          ),
          if (longNight) ...[
            const SizedBox(height: 12),
            Semantics(
              liveRegion: true,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.cannotSoft,
                  border: Border.all(color: AppColors.cannot, width: 2),
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'To ${hoursCount(spanHours(_from, _to))} godzin: od ${shortTime(_from)} do ${shortTime(_to)} '
                      'następnego dnia. Może godziny są zamienione?',
                      style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.cannot),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton(
                      onPressed: () => setState(() {
                        final from = _from;
                        _from = _to;
                        _to = from;
                      }),
                      child: Text('Zamień: od ${shortTime(_to)} do ${shortTime(_from)}'),
                    ),
                  ],
                ),
              ),
            ),
          ] else if (empty || overnight(draft)) ...[
            const SizedBox(height: 8),
            Text(
              empty
                  ? 'Początek i koniec są takie same. Zmień jedną z godzin.'
                  : 'Do ${shortTime(_to)} następnego dnia, na przykład na nockę.',
              style: TextStyle(fontSize: 14, color: empty ? AppColors.cannot : AppColors.inkMuted),
            ),
          ],
          const SizedBox(height: 12),
          if (two)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.surface,
                border: Border.all(color: AppColors.line),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      const Expanded(
                        child: Text('Drugi przedział', style: TextStyle(fontWeight: FontWeight.w600)),
                      ),
                      TextButton(onPressed: () => setState(() => _second = false), child: const Text('Usuń')),
                    ],
                  ),
                  const SizedBox(height: 4),
                  _Window(
                    from: _from2,
                    to: _to2,
                    onFrom: (value) => setState(() => _from2 = value),
                    onTo: (value) => setState(() => _to2 = value),
                  ),
                  const SizedBox(height: 12),
                  const Text('Ile zmian tego dnia?', style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  _Option(
                    chosen: !_oneShift,
                    title: 'Lub: mogę w obu',
                    detail: 'Możesz dostać zmianę w każdym z przedziałów.',
                    onTap: () => setState(() => _oneShift = false),
                  ),
                  const SizedBox(height: 8),
                  _Option(
                    chosen: _oneShift,
                    title: 'Albo: tylko jedna zmiana',
                    detail: 'Dostaniesz najwyżej jedną zmianę, w jednym z tych przedziałów.',
                    onTap: () => setState(() => _oneShift = true),
                  ),
                ],
              ),
            )
          else
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: () => setState(() => _second = true),
                child: const Text('Dodaj drugi przedział'),
              ),
            ),
          if (!empty) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: AppColors.paper,
                border: Border.all(color: AppColors.line),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Text(
                'Zmiany spoza godzin ${shortTime(_from)}–${_endWords(_to)}'
                '${two ? ' i ${shortTime(_from2)}–${_endWords(_to2)}' : ''} tego dnia nie dostaniesz.',
              ),
            ),
          ],
        ],
        const SizedBox(height: 20),
        FilledButton(
          onPressed: empty ? null : () => widget.onSave(draft),
          child: Text(longNight ? 'Tak, do ${shortTime(_to)} następnego dnia. Zapisz' : 'Zapisz ten dzień'),
        ),
      ],
    );
  }
}

/// "20" or "20,5": the hours of a long night in the warning.
String hoursCount(num hours) => hours.toString().replaceAll('.', ',');

/// A radio choice with a line of explanation, outlined when chosen.
class _Option extends StatelessWidget {
  const _Option({required this.chosen, required this.title, this.detail, required this.onTap});

  final bool chosen;
  final String title;
  final String? detail;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ChoiceBox(
      chosen: chosen,
      radio: true,
      onTap: onTap,
      alignment: Alignment.centerLeft,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          Icon(
            chosen ? Icons.radio_button_checked : Icons.radio_button_unchecked,
            color: chosen ? AppColors.accent : AppColors.inkMuted,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title),
                if (detail != null) Text(detail!, style: const TextStyle(fontSize: 14, color: AppColors.inkMuted)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// "Od" and "Do" side by side.
class _Window extends StatelessWidget {
  const _Window({required this.from, required this.to, required this.onFrom, required this.onTo});

  final String from;
  final String to;
  final ValueChanged<String> onFrom;
  final ValueChanged<String> onTo;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _TimeSelect(label: 'Od', value: from, onChanged: onFrom, asEnd: false),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _TimeSelect(label: 'Do', value: to, onChanged: onTo, asEnd: true),
        ),
      ],
    );
  }
}

class _TimeSelect extends StatelessWidget {
  const _TimeSelect({required this.label, required this.value, required this.onChanged, required this.asEnd});

  final String label;
  final String value;
  final ValueChanged<String> onChanged;
  final bool asEnd;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      // A new value from outside ("Zamień") replaces what the field shows.
      key: ValueKey(value),
      initialValue: value,
      isExpanded: true,
      menuMaxHeight: 320,
      decoration: InputDecoration(labelText: label),
      style: const TextStyle(fontSize: 18, color: AppColors.ink, fontFeatures: [FontFeature.tabularFigures()]),
      items: [
        for (final time in _timesWith(value))
          DropdownMenuItem(
            value: time,
            child: Text(_timeLabel(time, asEnd: asEnd)),
          ),
      ],
      onChanged: (time) {
        if (time != null) onChanged(time);
      },
    );
  }
}
