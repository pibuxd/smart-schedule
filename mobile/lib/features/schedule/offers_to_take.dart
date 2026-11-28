import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../../api/client.dart';
import '../../api/errors.dart';
import '../../api/generated/exports.dart';
import '../../shared/dates.dart';
import '../../ui/fold.dart';
import '../../ui/sheet.dart';
import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'rows.dart';
import 'schedule_data.dart';

/// "Zmiany do wzięcia": shifts that colleagues give away and that I can take (the server checks my calendar, my other
/// shifts and the position). "Weź zmianę" asks the manager; the shift is mine only after they approve. When the
/// shift's location hands shifts over without approval (`at_once`), it is mine right away. Folded at first, with the
/// count in the heading, so a long list does not push my own schedule down (Piotr, 22.11.2026). Hidden when there is
/// nothing to take. A tapped notification about one of them ([focus]) opens the list with that shift outlined.
class OffersToTake extends ConsumerStatefulWidget {
  const OffersToTake({super.key, required this.companyId, required this.readOnly, this.focus, this.focusKey});

  final String companyId;
  final bool readOnly;
  final String? focus;

  /// Given to the outlined offer, so the screen can scroll to it.
  final GlobalKey? focusKey;

  @override
  ConsumerState<OffersToTake> createState() => _OffersToTakeState();
}

class _OffersToTakeState extends ConsumerState<OffersToTake> {
  bool _taken = false;

  @override
  Widget build(BuildContext context) {
    final offers = ref.watch(availableOffersProvider(widget.companyId));
    // Space under it only when it shows something, so an empty list leaves no gap at the top of the screen.
    final note = _taken
        ? Padding(
            padding: const EdgeInsets.only(bottom: 20),
            child: _TakenNote(onClose: () => setState(() => _taken = false)),
          )
        : null;
    final list = offers.value;
    if (list == null) {
      if (offers.hasError) {
        return InlineError(errorMessage(offers.error, 'Nie udało się sprawdzić, czy są zmiany do wzięcia.'));
      }
      return note ?? const SizedBox.shrink();
    }
    if (list.isEmpty) return note ?? const SizedBox.shrink();
    final waiting = list.where((offer) => offer.myClaimStatus == AvailableOfferOutMyClaimStatus.pending).length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ?note,
        Fold(
          title: 'Zmiany do wzięcia',
          initiallyOpen: list.any((offer) => offer.id == widget.focus),
          status: TextSpan(
            children: [
              TextSpan(
                text: shiftsWord(list.length),
                style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.accent),
              ),
              if (waiting > 0) ...[
                const TextSpan(
                  text: ' · ',
                  style: TextStyle(color: AppColors.inkMuted),
                ),
                TextSpan(
                  text: 'czeka na kierownika: $waiting',
                  style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.preferNot),
                ),
              ],
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final offer in list) ...[
                _OfferCard(
                  key: offer.id == widget.focus ? widget.focusKey : ValueKey(offer.id),
                  offer: offer,
                  readOnly: widget.readOnly,
                  focused: offer.id == widget.focus,
                  onTaken: () => setState(() => _taken = true),
                ),
                const SizedBox(height: 12),
              ],
            ],
          ),
        ),
        const SizedBox(height: 20),
      ],
    );
  }
}

/// Shown in place of the list after a shift became mine at once (the card itself is gone from the list).
class _TakenNote extends StatelessWidget {
  const _TakenNote({required this.onClose});

  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.accentSoft,
          border: Border.all(color: AppColors.accent, width: 2),
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Zmiana jest Twoja.', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            const Text('Masz ją już w swoim grafiku. Przyjdź do pracy o tej godzinie.'),
            const SizedBox(height: 8),
            OutlinedButton(
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, touch)),
              onPressed: onClose,
              child: const Text('Rozumiem'),
            ),
          ],
        ),
      ),
    );
  }
}

class _OfferCard extends ConsumerStatefulWidget {
  const _OfferCard({
    super.key,
    required this.offer,
    required this.readOnly,
    required this.focused,
    required this.onTaken,
  });

  final AvailableOfferOut offer;
  final bool readOnly;
  final bool focused;
  final VoidCallback onTaken;

  @override
  ConsumerState<_OfferCard> createState() => _OfferCardState();
}

class _OfferCardState extends ConsumerState<_OfferCard> {
  // One more tap before the manager gets a request: an accidental touch should not sign someone up for a shift.
  bool _asking = false;
  bool _busy = false;
  Object? _error;

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
      if (mounted) {
        setState(() {
          _busy = false;
          _asking = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final offer = widget.offer;
    final shift = offer.shift;
    final api = ref.read(apiProvider);
    final waiting = offer.myClaimStatus == AvailableOfferOutMyClaimStatus.pending;
    final kind = shift.shiftTypeName.isEmpty ? '' : ', ${shift.shiftTypeName.toLowerCase()}';
    final claimId = offer.myClaimId;

    return FocusOutline(
      focused: widget.focused,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(color: AppColors.accent, width: 2),
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(dayTitle(parseDate(shift.date)), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            Text(
              '${shortTime(shift.startTime)}–${shortTime(shift.endTime)}',
              style: const TextStyle(
                fontSize: 21,
                fontWeight: FontWeight.w800,
                fontFeatures: [FontFeature.tabularFigures()],
              ),
            ),
            Text('${shift.positionName}$kind', style: const TextStyle(fontWeight: FontWeight.w600)),
            Text(
              '${shift.locationName}${offer.away ? ' (inny lokal)' : ''}. Oddaje: ${offer.offeredByName}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            if (waiting) ...[
              Semantics(
                liveRegion: true,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: AppColors.accentSoft,
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                  ),
                  child: const Text(
                    'Zgłoszone. Kierownik musi to zatwierdzić. Damy Ci znać.',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ),
              TextButton(
                onPressed: _busy || widget.readOnly || claimId == null
                    ? null
                    : () => _run(() async {
                        await api.marketplace.withdrawMyClaim(claimId: claimId);
                        refreshSchedule(ref);
                      }),
                child: const Text('Zrezygnuj'),
              ),
            ] else if (_asking) ...[
              Text(
                offer.atOnce
                    ? 'Wziąć tę zmianę? Od razu będzie Twoja i trzeba będzie na nią przyjść.'
                    : 'Wziąć tę zmianę? Kierownik dostanie Twoje zgłoszenie.',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: _busy || widget.readOnly
                    ? null
                    : () => _run(() async {
                        final claimed = await api.marketplace.claimOffer(offerId: offer.id);
                        if (claimed.myClaimStatus == AvailableOfferOutMyClaimStatus.approved) widget.onTaken();
                        refreshSchedule(ref);
                      }),
                child: Text(offer.atOnce ? 'Tak, biorę' : 'Tak, zgłoś mnie'),
              ),
              TextButton(onPressed: () => setState(() => _asking = false), child: const Text('Nie, jednak nie')),
            ] else
              FilledButton(
                onPressed: widget.readOnly ? null : () => setState(() => _asking = true),
                child: const Text('Weź zmianę'),
              ),
            if (_error != null) ...[const SizedBox(height: 8), InlineError(errorMessage(_error, networkProblem))],
          ],
        ),
      ),
    );
  }
}
