import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../shared/dates.dart';
import '../../ui/sheet.dart';
import '../../ui/status.dart';
import 'schedule_data.dart';

/// "Oddaj zmianę": everyone who could take the shift gets a notification; the shift stays mine until the manager
/// approves someone (or, with the location's rule "bez zatwierdzania", until someone takes it). While it is being
/// given away, "Jednak nie oddaję" takes the offer back.
Future<void> showGiveAwaySheet(BuildContext context, MyShiftOut shift) {
  return showAppSheet(
    context,
    title: shift.offerStatus != null ? 'Oddajesz tę zmianę' : 'Oddać tę zmianę?',
    description:
        '${dayTitle(parseDate(shift.date))}, ${shortTime(shift.startTime)}–${shortTime(shift.endTime)}, '
        '${shift.positionName}',
    builder: (context) => _GiveAway(shift: shift),
  );
}

class _GiveAway extends ConsumerStatefulWidget {
  const _GiveAway({required this.shift});

  final MyShiftOut shift;

  @override
  ConsumerState<_GiveAway> createState() => _GiveAwayState();
}

class _GiveAwayState extends ConsumerState<_GiveAway> {
  OfferMadeOut? _sent;
  Object? _error;
  bool _busy = false;

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
    final shift = widget.shift;
    final api = ref.read(apiProvider);
    final error = _error == null ? null : InlineError(errorMessage(_error, networkProblem));
    final sent = _sent;

    if (sent != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            liveRegion: true,
            child: Text(
              sent.notified > 0
                  ? '${_toldText(sent.notified, sent.notifiedHere)} '
                        '${sent.atOnce ? 'Gdy ktoś ją weźmie, od razu będzie jego, a Ty dostaniesz powiadomienie.' : 'Gdy ktoś się zgłosi, dostaniesz powiadomienie. Potem zdecyduje kierownik.'}'
                  : 'Teraz nikt nie może wziąć tej zmiany: inni pracują, zaznaczyli „nie mogę” albo mają inne '
                        'stanowisko. Zmiana czeka w „Zmiany do wzięcia”. Najlepiej porozmawiaj też z kierownikiem.',
            ),
          ),
          const SizedBox(height: 12),
          Text(_stillMine(sent.atOnce), style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 16),
          FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Rozumiem')),
        ],
      );
    }

    final offerId = shift.offerId;
    if (offerId != null) {
      final claimed = shift.offerStatus == MyShiftOutOfferStatus.claimed;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            claimed
                ? 'Ktoś chce wziąć tę zmianę. Teraz decyduje kierownik.'
                : shift.handoverAtOnce
                ? 'Jeszcze nikt jej nie wziął.'
                : 'Jeszcze nikt się nie zgłosił.',
          ),
          const SizedBox(height: 12),
          Text(
            '${_stillMine(shift.handoverAtOnce && !claimed)} Jeśli nic się nie zmieni, przyjdź do pracy.',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          if (error != null) ...[const SizedBox(height: 12), error],
          const SizedBox(height: 16),
          OutlinedButton(
            onPressed: _busy
                ? null
                : () => _run(() async {
                    await api.marketplace.cancelMyOffer(offerId: offerId);
                    refreshSchedule(ref);
                    if (context.mounted) Navigator.of(context).pop();
                  }),
            child: const Text('Jednak nie oddaję'),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Damy znać osobom, które mogą wziąć tę zmianę (także z innych lokali firmy). '
          '${shift.handoverAtOnce ? 'Pierwsza osoba, która ją weźmie, dostaje ją od razu.' : 'Gdy ktoś się zgłosi, kierownik zdecyduje.'}',
        ),
        const SizedBox(height: 12),
        Text(_stillMine(shift.handoverAtOnce), style: const TextStyle(fontWeight: FontWeight.w600)),
        if (error != null) ...[const SizedBox(height: 12), error],
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy
              ? null
              : () => _run(() async {
                  final made = await api.marketplace.offerMyShift(assignmentId: shift.id);
                  if (mounted) setState(() => _sent = made);
                  refreshSchedule(ref);
                }),
          child: const Text('Oddaj zmianę'),
        ),
      ],
    );
  }
}

String _stillMine(bool atOnce) => atOnce
    ? 'Dopóki nikt jej nie weźmie, to nadal Twoja zmiana.'
    : 'Dopóki kierownik nie zdecyduje, to nadal Twoja zmiana.';

String _dative(int count) => count == 1 ? 'jednej osobie' : '$count osobom';

/// "Daliśmy znać 38 osobom: 2 z Twojego lokalu i 36 z innych lokali firmy."
String _toldText(int all, int here) {
  final elsewhere = all - here;
  if (elsewhere == 0) {
    return 'Daliśmy znać ${_dative(all)} z Twojego lokalu, ${all == 1 ? 'która może' : 'które mogą'} wziąć tę zmianę.';
  }
  if (here == 0) {
    return 'Daliśmy znać ${_dative(all)} z innych lokali firmy. Z Twojego lokalu nikt nie może teraz jej wziąć.';
  }
  return 'Daliśmy znać ${_dative(all)}: $here z Twojego lokalu i $elsewhere z innych lokali firmy.';
}
