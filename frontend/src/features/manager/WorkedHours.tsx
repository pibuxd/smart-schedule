import { useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useState } from 'react'

import { useHandoverShifts } from '../../api/generated/marketplace/marketplace'
import type {
  HoursChangeOut,
  ManagerHoursChangesOut,
  ManagerOverviewOut,
  ManagerShiftOut,
  WaitingHoursOut,
  WorkedOut,
} from '../../api/generated/model'
import { useManagerOverview } from '../../api/generated/tenancy/tenancy'
import {
  useApproveHoursChange,
  useManagerHoursChanges,
  useRejectHoursChange,
  useSetShiftHours,
} from '../../api/generated/worktime/worktime'
import { Button } from '../../components/ui/button'
import { Section, SelectField, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { monthName, shiftMonth, shortTime, toIsoDate } from '../../lib/dates'
import { differenceSentence, differenceText, isTime, minutesBetween } from '../schedule/hours'
import { useManager } from './ManagerContext'
import { HOURS_REFRESH_MS } from './waiting-hours'
import { shortDay } from './words'

const REASON_MAX = 300

const range = (start: string, end: string) => `${shortTime(start)}–${shortTime(end)}`

// ----------------------------------------------------------------------------------------------- reports

/** "Zgłoszone godziny": overtime and shorter shifts waiting for a decision, and what was decided lately. */
export function HoursReports() {
  const { companyId, readOnly } = useManager()
  const changes = useManagerHoursChanges({ company_id: companyId }, { query: { refetchInterval: HOURS_REFRESH_MS } })
  if (changes.isPending) return <Loading>Wczytuję zgłoszone godziny…</Loading>
  if (changes.isError) {
    return (
      <ErrorState onRetry={() => void changes.refetch()}>
        {errorMessage(changes.error, 'Nie udało się wczytać zgłoszonych godzin. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = changes.data.data as ManagerHoursChangesOut
  const many = new Set([...data.pending, ...data.recent].map((c) => c.location_id)).size > 1
  return (
    <section aria-labelledby="hours-reports" className="grid gap-3">
      <h2 id="hours-reports" className="m-0 text-lg font-extrabold">
        Zgłoszone godziny
      </h2>
      {data.pending.length === 0 ? (
        <p className="m-0 text-ink-muted">Nikt nie czeka na decyzję o godzinach.</p>
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0">
          {data.pending.map((change) => (
            <PendingReport key={change.id} change={change} showLocation={many} readOnly={readOnly} />
          ))}
        </ul>
      )}
      {data.recent.length > 0 && (
        <Section collapsible title="Ostatnie decyzje" status={`${data.recent.length}`}>
          <ul className="m-0 grid list-none gap-2 p-0">
            {data.recent.map((change) => (
              <li key={change.id} className="grid gap-0.5 rounded-md border border-line bg-surface p-3 text-sm">
                <span>
                  <b>{change.employee_name}</b>, {shortDay(change.date)}: {range(change.start_time, change.end_time)}{' '}
                  zamiast {range(change.planned_start_time, change.planned_end_time)} (
                  {differenceText(change.difference_minutes)})
                </span>
                <span className={change.status === 'approved' ? 'text-prefer' : 'text-ink-muted'}>
                  {decisionWords(change)}
                  {many && ` · ${change.location_name}`}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </section>
  )
}

function decisionWords(change: HoursChangeOut): string {
  const who = change.decided_by_name ? ` (${change.decided_by_name})` : ''
  if (change.by_manager) return `Zmienione przez kierownika${who}`
  return change.status === 'approved' ? `Zatwierdzone${who}` : `Odrzucone${who}`
}

function PendingReport({
  change,
  showLocation,
  readOnly,
}: {
  change: HoursChangeOut
  showLocation: boolean
  readOnly: boolean
}) {
  const approve = useApproveHoursChange()
  const reject = useRejectHoursChange()
  const queryClient = useQueryClient()
  const done = { onSuccess: () => void queryClient.invalidateQueries() }
  const busy = readOnly || approve.isPending || reject.isPending
  return (
    <li className="grid gap-2 rounded-md border-2 border-ink bg-surface p-3">
      <div className="grid gap-0.5">
        <b>{change.employee_name}</b>
        <span className="text-sm text-ink-muted">
          {shortDay(change.date)}, {change.position_name}
          {showLocation && `, ${change.location_name}`}
        </span>
      </div>
      <p className="m-0">
        <span className="font-extrabold tabular-nums">{range(change.start_time, change.end_time)}</span> zamiast{' '}
        {range(change.planned_start_time, change.planned_end_time)}:{' '}
        <b>{differenceText(change.difference_minutes)}</b>
      </p>
      {change.reason && <p className="m-0 text-sm">Powód: {change.reason}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="normal" disabled={busy} onClick={() => approve.mutate({ changeId: change.id }, done)}>
          <Check aria-hidden="true" size={18} />
          Zatwierdź<span className="sr-only">: {change.employee_name}</span>
        </Button>
        <Button variant="secondary" size="normal" disabled={busy} onClick={() => reject.mutate({ changeId: change.id }, done)}>
          <X aria-hidden="true" size={18} />
          Odrzuć<span className="sr-only">: {change.employee_name}</span>
        </Button>
      </div>
      {(approve.isError || reject.isError) && (
        <InlineError>{errorMessage(approve.error ?? reject.error, NETWORK_PROBLEM)}</InlineError>
      )}
    </li>
  )
}

// ----------------------------------------------------------------------------------------------- the manager's own change

/** One person on one published shift: what the schedule says, what counts, a waiting report. */
export type HoursTarget = {
  assignmentId: string
  // The person shown: saving fails (409) when the shift went to someone else meanwhile.
  employeeId: string
  name: string
  date: string
  plannedStart: string
  plannedEnd: string
  worked?: WorkedOut | null
  report?: WaitingHoursOut | null
}

/**
 * "Zmień godziny": the hours a person really works (worked) on a published shift, saved at once (also after the
 * fact). The schedule's own hours bring the plan back. A waiting report of the shift is answered by this.
 */
export function WorkedHoursForm({ target, onDone }: { target: HoursTarget; onDone: () => void }) {
  const { readOnly } = useManager()
  const counted = target.worked ?? { start_time: target.plannedStart, end_time: target.plannedEnd }
  const [start, setStart] = useState(counted.start_time)
  const [end, setEnd] = useState(counted.end_time)
  const [reason, setReason] = useState('')
  const save = useSetShiftHours()
  const queryClient = useQueryClient()
  const valid = isTime(start) && isTime(end)
  const difference = valid ? minutesBetween(start, end) - minutesBetween(target.plannedStart, target.plannedEnd) : 0
  const same = valid && start === counted.start_time && end === counted.end_time && !target.report
  const submit = (from: string, to: string) =>
    save.mutate(
      {
        assignmentId: target.assignmentId,
        data: { employee_id: target.employeeId, start_time: from, end_time: to, reason: reason.trim() },
      },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries()
          onDone()
        },
      },
    )

  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (valid && !same) submit(start, end)
      }}
    >
      <p className="m-0">
        W grafiku {range(target.plannedStart, target.plannedEnd)}.
        {target.worked && ` Liczą się ${range(target.worked.start_time, target.worked.end_time)}.`}
      </p>
      {target.report && (
        <p className="m-0 rounded-md bg-paper p-3">
          {target.name} zgłasza {range(target.report.start_time, target.report.end_time)} (
          {differenceText(target.report.difference_minutes)}){target.report.reason && `. Powód: ${target.report.reason}`}.
          Twoje godziny zastąpią to zgłoszenie, a te same godziny je zatwierdzą.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3">
        <TextField label="Od" type="time" required value={start} onChange={(event) => setStart(event.target.value)} />
        <TextField label="Do" type="time" required value={end} onChange={(event) => setEnd(event.target.value)} />
      </div>
      <TextField
        label="Powód (nie musisz pisać)"
        value={reason}
        maxLength={REASON_MAX}
        onChange={(event) => setReason(event.target.value)}
      />
      <p role="status" className="m-0 font-semibold">
        {!valid
          ? 'Wpisz godziny od i do.'
          : same
            ? 'To te same godziny, które liczą się teraz.'
            : differenceSentence(difference)}
      </p>
      {save.isError && <InlineError>{errorMessage(save.error, NETWORK_PROBLEM)}</InlineError>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="normal" disabled={readOnly || save.isPending || !valid || same}>
          {save.isPending ? 'Zapisuję…' : 'Zapisz godziny'}
        </Button>
        {target.worked && (
          <Button
            variant="secondary"
            size="normal"
            disabled={readOnly || save.isPending}
            onClick={() => submit(target.plannedStart, target.plannedEnd)}
          >
            Przywróć godziny z grafiku
          </Button>
        )}
      </div>
      <p className="m-0 text-sm text-ink-muted">Zapisane godziny liczą się od razu. {target.name} dostanie powiadomienie.</p>
    </form>
  )
}

export function WorkedHoursSheet({ target, onClose }: { target: HoursTarget | null; onClose: () => void }) {
  return (
    <Sheet
      open={target !== null}
      onOpenChange={(open) => !open && onClose()}
      title={target ? `Godziny: ${target.name}` : ''}
      description={target ? shortDay(target.date) : undefined}
    >
      {target && <WorkedHoursForm key={target.assignmentId} target={target} onDone={onClose} />}
    </Sheet>
  )
}

function managerShiftTarget(row: ManagerShiftOut): HoursTarget {
  return {
    assignmentId: row.id,
    employeeId: row.employee_id!,
    name: row.employee_name,
    date: row.shift.date,
    plannedStart: row.shift.start_time,
    plannedEnd: row.shift.end_time,
    worked: row.worked,
    report: row.hours_report,
  }
}

/** "Zmień godziny sam": pick a location, a day and a person on a published shift. */
export function ChangeHours() {
  const { companyId } = useManager()
  const overview = useManagerOverview({ company_id: companyId })
  const locations = overview.isSuccess ? (overview.data.data as ManagerOverviewOut).locations : []
  const [chosen, setChosen] = useState('')
  const locationId = chosen || locations[0]?.id || ''
  return (
    <Section
      collapsible
      title="Zmień godziny sam"
      description="Ktoś został dłużej albo wyszedł wcześniej i nic nie zgłosił? Wpisz prawdziwe godziny pracy. Także po fakcie."
    >
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
          <LocationShifts key={locationId} locationId={locationId} />
        </>
      )}
    </Section>
  )
}

function LocationShifts({ locationId }: { locationId: string }) {
  const today = toIsoDate(new Date())
  const [month, setMonth] = useState(today.slice(0, 7))
  const move = (by: number) => setMonth(shiftMonth(month, by))
  return (
    <>
      <div className="flex items-center gap-2">
        <Button variant="quiet" size="normal" onClick={() => move(-1)} aria-label="Zmiany z poprzedniego miesiąca">
          <ChevronLeft aria-hidden="true" size={22} />
        </Button>
        <span className="min-w-40 text-center font-semibold">{monthName(month)}</span>
        <Button variant="quiet" size="normal" onClick={() => move(1)} aria-label="Zmiany z następnego miesiąca">
          <ChevronRight aria-hidden="true" size={22} />
        </Button>
      </div>
      <MonthShifts key={month} locationId={locationId} month={month} today={today} />
    </>
  )
}

/** The published shifts of one month (older ones too: the manager corrects hours with no time limit). */
function MonthShifts({ locationId, month, today }: { locationId: string; month: string; today: string }) {
  const { readOnly } = useManager()
  const shifts = useHandoverShifts(locationId, { month })
  const [day, setDay] = useState('')
  const [target, setTarget] = useState<HoursTarget | null>(null)
  if (shifts.isPending) return <Loading>Wczytuję zmiany…</Loading>
  if (shifts.isError) {
    return (
      <ErrorState onRetry={() => void shifts.refetch()}>
        {errorMessage(shifts.error, 'Nie udało się wczytać zmian. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const rows = (shifts.data.data as ManagerShiftOut[]).filter((s) => s.employee_id)
  const days = [...new Set(rows.map((s) => s.shift.date))].sort()
  if (days.length === 0) {
    return <p className="m-0 text-ink-muted">W tym miesiącu ten lokal nie ma opublikowanego grafiku.</p>
  }
  const shown = day || (days.includes(today) ? today : days.filter((d) => d < today).pop() ?? days[0])
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
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-surface p-3">
              <div className="grid gap-0.5">
                <b>{s.employee_name}</b>
                <span className="text-sm text-ink-muted">
                  {s.worked
                    ? `${range(s.worked.start_time, s.worked.end_time)} (w grafiku ${range(s.shift.start_time, s.shift.end_time)})`
                    : range(s.shift.start_time, s.shift.end_time)}
                  , {s.shift.position_name}
                </span>
                {s.hours_report && (
                  <span className="text-sm font-semibold text-prefer-not">
                    Zgłasza {range(s.hours_report.start_time, s.hours_report.end_time)}: czeka na decyzję
                  </span>
                )}
              </div>
              <Button variant="secondary" size="normal" disabled={readOnly} onClick={() => setTarget(managerShiftTarget(s))}>
                Zmień godziny<span className="sr-only">: {s.employee_name}</span>
              </Button>
            </li>
          ))}
      </ul>
      <WorkedHoursSheet target={target} onClose={() => setTarget(null)} />
    </>
  )
}
