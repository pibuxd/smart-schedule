import { useQueryClient } from '@tanstack/react-query'

import { useAvailableOffers, useClaimOffer, useWithdrawMyClaim } from '../../api/generated/marketplace/marketplace'
import type { AvailableOfferOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayTitle, parseDate, shortTime } from '../../lib/dates'

/**
 * "Zmiany do wzięcia": shifts that colleagues give away and that I can take (the server checks my calendar,
 * my other shifts and the position). "Biorę" asks the manager; the shift is mine only after they approve.
 * Hidden when there is nothing to take, so the schedule stays the first thing on the screen.
 */
export function OffersToTake({ companyId, readOnly }: { companyId: string; readOnly: boolean }) {
  const offers = useAvailableOffers({ company_id: companyId })
  if (offers.isPending) return null
  if (offers.isError) {
    return <InlineError>{errorMessage(offers.error, 'Nie udało się sprawdzić, czy są zmiany do wzięcia.')}</InlineError>
  }
  const list = offers.data.data as AvailableOfferOut[]
  if (list.length === 0) return null
  return (
    <section aria-labelledby="to-take" className="grid gap-3">
      <h2 id="to-take" className="m-0 text-lg font-extrabold">
        Zmiany do wzięcia
      </h2>
      <ul className="m-0 grid list-none gap-3 p-0">
        {list.map((offer) => (
          <OfferCard key={offer.id} offer={offer} readOnly={readOnly} />
        ))}
      </ul>
    </section>
  )
}

function OfferCard({ offer, readOnly }: { offer: AvailableOfferOut; readOnly: boolean }) {
  const claim = useClaimOffer()
  const withdraw = useWithdrawMyClaim()
  const queryClient = useQueryClient()
  const refresh = () => void queryClient.invalidateQueries()
  const { shift } = offer
  const waiting = offer.my_claim_status === 'pending'
  const error = claim.error ?? withdraw.error

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
            Zgłoszenie wysłane. Czekasz na decyzję kierownika i dostaniesz powiadomienie.
          </p>
          <Button
            variant="quiet"
            size="normal"
            disabled={withdraw.isPending || readOnly}
            onClick={() => withdraw.mutate({ claimId: offer.my_claim_id! }, { onSuccess: refresh })}
          >
            Jednak nie biorę
          </Button>
        </>
      ) : (
        <Button
          wide
          disabled={claim.isPending || readOnly}
          onClick={() => claim.mutate({ offerId: offer.id }, { onSuccess: refresh })}
        >
          Biorę
        </Button>
      )}
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
    </li>
  )
}
