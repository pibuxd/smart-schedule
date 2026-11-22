import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { useAvailableOffers, useClaimOffer, useWithdrawMyClaim } from '../../api/generated/marketplace/marketplace'
import type { AvailableOfferOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { Section } from '../../components/ui/field'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayTitle, parseDate, shortTime } from '../../lib/dates'
import { shifts as shiftsWord } from '../manager/words'

/**
 * "Zmiany do wzięcia": shifts that colleagues give away and that I can take (the server checks my calendar,
 * my other shifts and the position). "Weź zmianę" asks the manager; the shift is mine only after they approve.
 * When the shift's location hands shifts over without approval (`at_once`), it is mine right away.
 * Folded at first, with the count in the heading, so a long list does not push my own schedule down the screen
 * (Piotr, 22.11.2026). Hidden when there is nothing to take.
 */
export function OffersToTake({ companyId, readOnly }: { companyId: string; readOnly: boolean }) {
  const offers = useAvailableOffers({ company_id: companyId })
  const [taken, setTaken] = useState(false)
  const note = taken ? <TakenNote onClose={() => setTaken(false)} /> : null
  if (offers.isPending) return note
  if (offers.isError) {
    return <InlineError>{errorMessage(offers.error, 'Nie udało się sprawdzić, czy są zmiany do wzięcia.')}</InlineError>
  }
  const list = offers.data.data as AvailableOfferOut[]
  if (list.length === 0) return note
  const waiting = list.filter((offer) => offer.my_claim_status === 'pending').length
  return (
    <>
      {note}
      <Section
        collapsible
        title="Zmiany do wzięcia"
        status={
          <>
            <span className="font-semibold text-accent">{shiftsWord(list.length)}</span>
            {waiting > 0 && (
              <>
                <span className="text-ink-muted"> · </span>
                <span className="font-semibold text-prefer-not">czeka na kierownika: {waiting}</span>
              </>
            )}
          </>
        }
      >
        <ul className="m-0 grid list-none gap-3 p-0">
          {list.map((offer) => (
            <OfferCard key={offer.id} offer={offer} readOnly={readOnly} onTaken={() => setTaken(true)} />
          ))}
        </ul>
      </Section>
    </>
  )
}

/** Shown in place of the list after a shift became mine at once (the card itself is gone from the list). */
function TakenNote({ onClose }: { onClose: () => void }) {
  return (
    <div role="status" className="grid gap-2 rounded-lg border-2 border-accent bg-accent-soft p-4">
      <b className="text-lg">Zmiana jest Twoja.</b>
      <p className="m-0">Masz ją już w swoim grafiku. Przyjdź do pracy o tej godzinie.</p>
      <Button variant="secondary" size="normal" onClick={onClose}>
        Rozumiem
      </Button>
    </div>
  )
}

function OfferCard({
  offer,
  readOnly,
  onTaken,
}: {
  offer: AvailableOfferOut
  readOnly: boolean
  onTaken: () => void
}) {
  const claim = useClaimOffer()
  const withdraw = useWithdrawMyClaim()
  const queryClient = useQueryClient()
  const refresh = () => void queryClient.invalidateQueries()
  const { shift } = offer
  const waiting = offer.my_claim_status === 'pending'
  const error = claim.error ?? withdraw.error
  // One more tap before the manager gets a request: an accidental touch should not sign someone up for a shift.
  const [asking, setAsking] = useState(false)

  return (
    <li className="grid gap-3 rounded-lg border-2 border-accent bg-surface p-4">
      <div className="grid gap-0.5">
        <b className="text-lg">{dayTitle(parseDate(shift.date))}</b>
        <span className="text-xl font-extrabold tabular-nums">
          {shortTime(shift.start_time)}–{shortTime(shift.end_time)}
        </span>
        <span className="font-semibold">
          {shift.position_name}
          {shift.shift_type_name ? `, ${shift.shift_type_name.toLowerCase()}` : ''}
        </span>
        <span className="text-sm text-ink-muted">
          {shift.location_name}
          {offer.away ? ' (inny lokal)' : ''}. Oddaje: {offer.offered_by_name}
        </span>
      </div>
      {waiting ? (
        <>
          <p role="status" className="m-0 rounded-sm bg-accent-soft px-3 py-2 font-semibold">
            Zgłoszone. Kierownik musi to zatwierdzić. Damy Ci znać.
          </p>
          <Button
            variant="quiet"
            size="normal"
            disabled={withdraw.isPending || readOnly}
            onClick={() => withdraw.mutate({ claimId: offer.my_claim_id! }, { onSuccess: refresh })}
          >
            Zrezygnuj
          </Button>
        </>
      ) : asking ? (
        <div className="grid gap-2">
          <p className="m-0 font-semibold">
            {offer.at_once
              ? 'Wziąć tę zmianę? Od razu będzie Twoja i trzeba będzie na nią przyjść.'
              : 'Wziąć tę zmianę? Kierownik dostanie Twoje zgłoszenie.'}
          </p>
          <Button
            wide
            disabled={claim.isPending || readOnly}
            onClick={() =>
              claim.mutate(
                { offerId: offer.id },
                {
                  onSuccess: (response) => {
                    if ((response.data as AvailableOfferOut).my_claim_status === 'approved') onTaken()
                    refresh()
                  },
                  onSettled: () => setAsking(false),
                },
              )
            }
          >
            {offer.at_once ? 'Tak, biorę' : 'Tak, zgłoś mnie'}
          </Button>
          <Button variant="quiet" size="normal" wide onClick={() => setAsking(false)}>
            Nie, jednak nie
          </Button>
        </div>
      ) : (
        <Button wide disabled={readOnly} onClick={() => setAsking(true)}>
          Weź zmianę
        </Button>
      )}
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
    </li>
  )
}
