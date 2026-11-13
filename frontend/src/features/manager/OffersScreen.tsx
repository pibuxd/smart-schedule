import { useQueryClient } from '@tanstack/react-query'

import { useApproveClaim, useManagerOffers, useRejectClaim } from '../../api/generated/marketplace/marketplace'
import type { ClaimOut, ManagerOfferOut, ManagerOffersOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { shortTime } from '../../lib/dates'
import { useManager } from './ManagerContext'
import { OFFERS_REFRESH_MS } from './waiting-claims'
import { shortDay } from './words'

const STATUS: Record<ManagerOfferOut['status'], string> = {
  open: 'Czeka na chętnego',
  claimed: 'Czeka na Twoją decyzję',
  approved: 'Zatwierdzona',
  rejected: 'Odrzucona',
  cancelled: 'Wycofana przez pracownika',
  expired: 'Nieaktualna',
}

const CLAIM_STATUS: Record<ClaimOut['status'], string> = {
  pending: 'czeka',
  approved: 'zatwierdzona',
  rejected: 'odrzucona',
  withdrawn: 'wycofała się',
}

/**
 * "Oddane zmiany": shifts employees give away in my locations. For each volunteer ("Biorę") the manager sees
 * whether they can still take the shift (checked again by the validator) and approves one or rejects.
 * Approving changes the published schedule right away and tells everyone involved in the app.
 */
export function OffersScreen() {
  const { companyId, readOnly } = useManager()
  const offers = useManagerOffers({ company_id: companyId }, { query: { refetchInterval: OFFERS_REFRESH_MS } })

  return (
    <div className="grid gap-6">
      <div className="grid gap-1">
        <h1 className="m-0 text-2xl font-extrabold">Oddane zmiany</h1>
        <p className="m-0 max-w-[62ch] text-ink-muted">
          Pracownik oddaje zmianę, a osoby, które mogą ją wziąć, dostają powiadomienie. Gdy ktoś powie „Biorę”,
          decydujesz tutaj. Po zatwierdzeniu zmiana od razu przechodzi w opublikowanym grafiku i jest przypięta.
        </p>
      </div>
      {offers.isPending ? (
        <Loading>Wczytuję oddane zmiany…</Loading>
      ) : offers.isError ? (
        <ErrorState onRetry={() => void offers.refetch()}>
          {errorMessage(offers.error, 'Nie udało się wczytać oddanych zmian. Spróbuj jeszcze raz.')}
        </ErrorState>
      ) : (offers.data.data as ManagerOffersOut).offers.length === 0 ? (
        <EmptyState title="Nikt nie oddaje teraz zmian">
          <p className="m-0">
            Gdy pracownik odda zmianę w „Mój grafik”, zobaczysz ją tutaj razem z osobami, które chcą ją wziąć.
          </p>
        </EmptyState>
      ) : (
        <OfferList offers={(offers.data.data as ManagerOffersOut).offers} readOnly={readOnly} />
      )}
    </div>
  )
}

function OfferList({ offers, readOnly }: { offers: ManagerOfferOut[]; readOnly: boolean }) {
  const active = offers.filter((o) => o.status === 'open' || o.status === 'claimed')
  const done = offers.filter((o) => o.status !== 'open' && o.status !== 'claimed')
  return (
    <>
      {active.length > 0 ? (
        <ul className="m-0 grid list-none gap-4 p-0">
          {active.map((offer) => (
            <OfferCard key={offer.id} offer={offer} readOnly={readOnly} />
          ))}
        </ul>
      ) : (
        <p className="m-0 text-ink-muted">Nic nie czeka na decyzję.</p>
      )}
      {done.length > 0 && (
        <section aria-labelledby="done-offers" className="grid gap-3">
          <h2 id="done-offers" className="m-0 text-lg font-extrabold">
            Ostatnie dwa tygodnie
          </h2>
          <ul className="m-0 grid list-none gap-3 p-0">
            {done.map((offer) => (
              <OfferCard key={offer.id} offer={offer} readOnly />
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

function OfferCard({ offer, readOnly }: { offer: ManagerOfferOut; readOnly: boolean }) {
  const { shift } = offer
  const pending = offer.claims.filter((c) => c.status === 'pending')
  const decided = offer.claims.filter((c) => c.status !== 'pending')
  const waiting = offer.status === 'claimed'
  return (
    <li className={`grid gap-3 rounded-lg border bg-surface p-4 ${waiting ? 'border-2 border-accent' : 'border-line'}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="grid gap-0.5">
          <b className="text-lg">
            {shortDay(shift.date)}, {shortTime(shift.start_time)}–{shortTime(shift.end_time)}
          </b>
          <span>
            {shift.position_name}
            {shift.shift_type_name ? `, ${shift.shift_type_name.toLowerCase()}` : ''}, {shift.location_name}
          </span>
          <span className="text-sm text-ink-muted">Oddaje: {offer.offered_by_name}</span>
        </div>
        <span className={`font-semibold ${waiting ? 'text-accent' : 'text-ink-muted'}`}>{STATUS[offer.status]}</span>
      </div>
      {pending.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {pending.map((claim) => (
            <ClaimRow key={claim.id} claim={claim} location={shift.location_name} readOnly={readOnly} />
          ))}
        </ul>
      )}
      {decided.length > 0 && (
        <p className="m-0 text-sm text-ink-muted">
          {decided.map((c) => `${c.name} (${CLAIM_STATUS[c.status]})`).join(', ')}
        </p>
      )}
    </li>
  )
}

function ClaimRow({ claim, location, readOnly }: { claim: ClaimOut; location: string; readOnly: boolean }) {
  const approve = useApproveClaim()
  const reject = useRejectClaim()
  const queryClient = useQueryClient()
  const refresh = () => void queryClient.invalidateQueries()
  const busy = approve.isPending || reject.isPending
  const possible = claim.problems.length === 0
  const error = approve.error ?? reject.error
  return (
    <li className="grid gap-2 rounded-md border border-line bg-paper p-3">
      <div className="grid gap-0.5">
        <span className="font-semibold">Chce wziąć: {claim.name}</span>
        {claim.home_location_name !== location && (
          <span className="text-sm text-ink-muted">Na co dzień: {claim.home_location_name}</span>
        )}
        {claim.problems.map((problem) => (
          <span key={problem} className="text-sm text-cannot">
            {problem}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="normal"
          disabled={readOnly || busy || !possible}
          onClick={() => approve.mutate({ claimId: claim.id }, { onSuccess: refresh })}
        >
          Zatwierdź: {claim.name}
        </Button>
        <Button
          variant="secondary"
          size="normal"
          disabled={readOnly || busy}
          onClick={() => reject.mutate({ claimId: claim.id }, { onSuccess: refresh })}
        >
          Odrzuć
        </Button>
      </div>
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
    </li>
  )
}
