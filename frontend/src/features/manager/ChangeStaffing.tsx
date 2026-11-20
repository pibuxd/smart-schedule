import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  useCheckShiftSwap,
  useHandoverCandidates,
  useHandoverShifts,
  useOfferShiftForEmployee,
  useReassignShift,
  useSwapShifts,
} from '../../api/generated/marketplace/marketplace'
import type { HandoverCandidateOut, ManagerShiftOut, OfferShiftOut, SwapCheckOut } from '../../api/generated/model'
import { useManagerOverview } from '../../api/generated/tenancy/tenancy'
import type { ManagerOverviewOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { SelectField, Tag } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { shortTime, toIsoDate } from '../../lib/dates'
import { useManager } from './ManagerContext'
import { shortDay } from './words'

/** The shift the manager changes: a row of "Zmień obsadę" or the shift of an offer. */
export type ShiftTarget = {
  id: string // the published assignment
  shift: OfferShiftOut
  employee_name: string
  started: boolean
  offer_id?: string | null
}

const NOT_PINNED = 'Zmiana wbrew zasadom nie będzie przypięta. Ponowne układanie grafiku może ją zmienić.'

const hoursOf = (shift: OfferShiftOut) => `${shortTime(shift.start_time)}–${shortTime(shift.end_time)}`

/** Days that have shifts, and the one to open first: today, or the nearest day after it. */
function daysOf(shifts: ManagerShiftOut[], today = toIsoDate(new Date())) {
  const days = [...new Set(shifts.map((s) => s.shift.date))].sort()
  return { days, first: days.find((d) => d >= today) ?? days[days.length - 1] ?? '' }
}

/**
 * "Zmień obsadę": the manager picks a published shift of a location and changes who works it, without anyone's
 * "Weź zmianę". Also for shifts that have already passed, so the hours say who really worked.
 */
export function ChangeStaffing() {
  const { companyId, readOnly } = useManager()
  const overview = useManagerOverview({ company_id: companyId })
  const locations = overview.isSuccess ? (overview.data.data as ManagerOverviewOut).locations : []
  const [chosen, setChosen] = useState('')
  const locationId = chosen || locations[0]?.id || ''

  return (
    <section aria-labelledby="change-staffing" className="grid gap-3">
      <div className="grid gap-1">
        <h2 id="change-staffing" className="m-0 text-lg font-extrabold">
          Zmień obsadę sam
        </h2>
        <p className="m-0 text-sm text-ink-muted">
          Wpisz inną osobę albo zamień dwie osoby w opublikowanym grafiku. Także po fakcie.
        </p>
      </div>
      {overview.isPending ? (
        <Loading>Wczytuję lokale…</Loading>
      ) : overview.isError ? (
        <ErrorState onRetry={() => void overview.refetch()}>
          {errorMessage(overview.error, 'Nie udało się wczytać lokali. Spróbuj jeszcze raz.')}
        </ErrorState>
      ) : locations.length === 0 ? (
        <p className="m-0 text-ink-muted">Nie masz jeszcze żadnego lokalu.</p>
      ) : (
        <>
          {locations.length > 1 && (
            <SelectField label="Lokal" value={locationId} onChange={(e) => setChosen(e.target.value)}>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </SelectField>
          )}
          <LocationShifts key={locationId} locationId={locationId} readOnly={readOnly} />
        </>
      )}
    </section>
  )
}

function LocationShifts({ locationId, readOnly }: { locationId: string; readOnly: boolean }) {
  const shifts = useHandoverShifts(locationId)
  const [day, setDay] = useState('')
  const [target, setTarget] = useState<ManagerShiftOut | null>(null)
  if (shifts.isPending) return <Loading>Wczytuję zmiany…</Loading>
  if (shifts.isError) {
    return (
      <ErrorState onRetry={() => void shifts.refetch()}>
        {errorMessage(shifts.error, 'Nie udało się wczytać zmian. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const rows = shifts.data.data as ManagerShiftOut[]
  const { days, first } = daysOf(rows)
  if (days.length === 0) return <p className="m-0 text-ink-muted">Ten lokal nie ma opublikowanego grafiku.</p>
  const shown = day || first
  return (
    <>
      <SelectField label="Dzień" value={shown} onChange={(e) => setDay(e.target.value)}>
        {days.map((d) => (
          <option key={d} value={d}>
            {shortDay(d)}
          </option>
        ))}
      </SelectField>
      <ul className="m-0 grid list-none gap-2 p-0">
        {rows
          .filter((s) => s.shift.date === shown)
          .map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-surface p-3"
            >
              <div className="grid gap-0.5">
                <b>{s.employee_name || 'Bez obsady'}</b>
                <span className="text-sm text-ink-muted">
                  {hoursOf(s.shift)}, {s.shift.position_name}
                  {s.offer_id ? ' · oddawana' : ''}
                </span>
              </div>
              <Button variant="secondary" size="normal" disabled={readOnly} onClick={() => setTarget(s)}>
                Zmień<span className="sr-only">: {s.employee_name || 'bez obsady'}, {hoursOf(s.shift)}</span>
              </Button>
            </li>
          ))}
      </ul>
      {target && <ShiftChangeSheet target={target} onClose={() => setTarget(null)} />}
    </>
  )
}

/** One published shift: put another person on it, swap it with another shift, or look for volunteers. */
export function ShiftChangeSheet({ target, onClose }: { target: ShiftTarget; onClose: () => void }) {
  const [swapping, setSwapping] = useState(false)
  const queryClient = useQueryClient()
  const done = () => {
    void queryClient.invalidateQueries()
    onClose()
  }
  const { shift } = target
  return (
    <Sheet
      open
      onOpenChange={(open) => !open && onClose()}
      title={swapping ? 'Zamień z inną zmianą' : 'Zmień osobę'}
      description={`${shortDay(shift.date)}, ${hoursOf(shift)}, ${shift.position_name}. Teraz: ${
        target.employee_name || 'bez obsady'
      }.`}
    >
      {swapping ? (
        <SwapPicker target={target} onBack={() => setSwapping(false)} onDone={done} />
      ) : (
        <PersonPicker target={target} onSwap={() => setSwapping(true)} onDone={done} />
      )}
    </Sheet>
  )
}

function PersonPicker({ target, onSwap, onDone }: { target: ShiftTarget; onSwap: () => void; onDone: () => void }) {
  const candidates = useHandoverCandidates(target.id)
  const reassign = useReassignShift()
  const offer = useOfferShiftForEmployee()
  const busy = reassign.isPending || offer.isPending
  const error = reassign.error ?? offer.error
  const canOffer = !!target.employee_name && !target.started && !target.offer_id
  const all = candidates.isSuccess ? (candidates.data.data as HandoverCandidateOut[]) : []
  // The server's order (can come, wants it, name) holds inside each group.
  const here = all.filter((c) => c.here)
  const away = all.filter((c) => !c.here)
  const wantingAway = away.filter((c) => c.wants).length
  const put = (c: HandoverCandidateOut) =>
    reassign.mutate(
      { assignmentId: target.id, data: { employee_id: c.employee_id, force: c.problems.length > 0 } },
      { onSuccess: onDone },
    )
  return (
    <div className="grid gap-4">
      {candidates.isPending ? (
        <Loading>Sprawdzam, kto może przyjść…</Loading>
      ) : candidates.isError ? (
        <ErrorState onRetry={() => void candidates.refetch()}>
          {errorMessage(candidates.error, 'Nie udało się sprawdzić osób. Spróbuj jeszcze raz.')}
        </ErrorState>
      ) : all.length === 0 ? (
        <p className="m-0 text-ink-muted">Nie ma innej osoby, którą można tu wpisać.</p>
      ) : (
        <>
          {here.length > 0 ? (
            <CandidateList candidates={here} busy={busy} onPut={put} />
          ) : (
            <p className="m-0 text-ink-muted">Z tego lokalu nie ma kogo tu wpisać.</p>
          )}
          {away.length > 0 && (
            // People who do not work in the shift's location: folded, so the location's own people come first.
            // Open at once when there is nobody else to pick.
            <details className="grid gap-2" open={here.length === 0 || undefined}>
              <summary className="min-h-(--touch) cursor-pointer content-center font-semibold text-accent">
                Z innych lokali ({away.length})
                {wantingAway > 0 && (
                  <>
                    {' '}
                    <Tag tone="accent">chce wziąć: {wantingAway}</Tag>
                  </>
                )}
              </summary>
              <div className="mt-2">
                <CandidateList candidates={away} busy={busy} onPut={put} />
              </div>
            </details>
          )}
        </>
      )}
      {all.some((c) => c.problems.length > 0) && <p className="m-0 text-sm text-ink-muted">{NOT_PINNED}</p>}
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
      <div className="flex flex-wrap gap-2">
        {target.employee_name && (
          <Button variant="secondary" size="normal" disabled={busy} onClick={onSwap}>
            Zamień z inną zmianą
          </Button>
        )}
        {canOffer && (
          <Button
            variant="secondary"
            size="normal"
            disabled={busy}
            onClick={() => offer.mutate({ assignmentId: target.id }, { onSuccess: onDone })}
          >
            Poszukaj chętnych
          </Button>
        )}
      </div>
    </div>
  )
}

function CandidateList({
  candidates,
  busy,
  onPut,
}: {
  candidates: HandoverCandidateOut[]
  busy: boolean
  onPut: (candidate: HandoverCandidateOut) => void
}) {
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {candidates.map((c) => (
        <li key={c.employee_id} className="grid gap-2 rounded-md border border-line bg-surface p-3">
          <div className="grid gap-0.5">
            <span className="flex flex-wrap items-center gap-2 font-semibold">
              {c.name}
              {c.wants && <Tag tone="accent">chce wziąć</Tag>}
              {!c.here && <Tag>{c.home_location_name}</Tag>}
            </span>
            {c.problems.map((problem) => (
              <span key={problem} className="text-sm text-cannot">
                {problem}
              </span>
            ))}
          </div>
          <Button
            size="normal"
            variant={c.problems.length ? 'danger' : 'primary'}
            disabled={busy}
            onClick={() => onPut(c)}
          >
            {c.problems.length ? 'Wpisz mimo to' : 'Wpisz'}: {c.name}
          </Button>
        </li>
      ))}
    </ul>
  )
}

function SwapPicker({ target, onBack, onDone }: { target: ShiftTarget; onBack: () => void; onDone: () => void }) {
  const shifts = useHandoverShifts(target.shift.location_id)
  const check = useCheckShiftSwap()
  const swap = useSwapShifts()
  const [day, setDay] = useState('')
  const [other, setOther] = useState<ManagerShiftOut | null>(null)
  if (shifts.isPending) return <Loading>Wczytuję zmiany…</Loading>
  if (shifts.isError) {
    return (
      <ErrorState onRetry={() => void shifts.refetch()}>
        {errorMessage(shifts.error, 'Nie udało się wczytać zmian. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const all = shifts.data.data as ManagerShiftOut[]
  const mine = all.find((s) => s.id === target.id)
  // Only shifts of the same published schedule, held by someone else.
  const rows = all.filter(
    (s) => s.id !== target.id && s.employee_id && s.employee_id !== mine?.employee_id && s.version_id === mine?.version_id,
  )
  const { days } = daysOf(rows)
  const shown = day || (days.includes(target.shift.date) ? target.shift.date : (days[0] ?? ''))
  const problems = check.isSuccess ? (check.data.data as SwapCheckOut).problems : []
  const pick = (s: ManagerShiftOut) => {
    setOther(s)
    swap.reset()
    check.mutate({ data: { first_id: target.id, second_id: s.id } })
  }
  return (
    <div className="grid gap-4">
      {days.length === 0 ? (
        <p className="m-0 text-ink-muted">W tym grafiku nie ma zmiany innej osoby do zamiany.</p>
      ) : (
        <>
          <SelectField label="Dzień drugiej zmiany" value={shown} onChange={(e) => setDay(e.target.value)}>
            {days.map((d) => (
              <option key={d} value={d}>
                {shortDay(d)}
              </option>
            ))}
          </SelectField>
          <ul className="m-0 grid list-none gap-2 p-0">
            {rows
              .filter((s) => s.shift.date === shown)
              .map((s) => (
                <li key={s.id}>
                  <Button
                    wide
                    size="normal"
                    variant="secondary"
                    aria-pressed={other?.id === s.id}
                    className={other?.id === s.id ? 'bg-accent-soft' : ''}
                    onClick={() => pick(s)}
                  >
                    {s.employee_name}, {hoursOf(s.shift)}, {s.shift.position_name}
                  </Button>
                </li>
              ))}
          </ul>
        </>
      )}
      {other && (
        <div className="grid gap-2 rounded-md border border-line bg-surface p-3" aria-live="polite">
          <span className="font-semibold">
            {target.employee_name} ↔ {other.employee_name}
          </span>
          <span className="text-sm text-ink-muted">
            {target.employee_name}: {shortDay(other.shift.date)}, {hoursOf(other.shift)}. {other.employee_name}:{' '}
            {shortDay(target.shift.date)}, {hoursOf(target.shift)}.
          </span>
          {check.isPending && <span className="text-sm text-ink-muted">Sprawdzam zamianę…</span>}
          {problems.map((problem) => (
            <span key={problem} className="text-sm text-cannot">
              {problem}
            </span>
          ))}
          {problems.length > 0 && <span className="text-sm text-ink-muted">{NOT_PINNED}</span>}
          {check.isSuccess && (
            <Button
              size="normal"
              variant={problems.length ? 'danger' : 'primary'}
              disabled={swap.isPending}
              onClick={() =>
                swap.mutate(
                  { data: { first_id: target.id, second_id: other.id, force: problems.length > 0 } },
                  { onSuccess: onDone },
                )
              }
            >
              {problems.length ? 'Zamień mimo to' : 'Zamień'}
            </Button>
          )}
          {(check.error ?? swap.error) && (
            <InlineError>{errorMessage(check.error ?? swap.error, NETWORK_PROBLEM)}</InlineError>
          )}
        </div>
      )}
      <div>
        <Button variant="quiet" size="normal" onClick={onBack}>
          Wróć do wyboru osoby
        </Button>
      </div>
    </div>
  )
}
