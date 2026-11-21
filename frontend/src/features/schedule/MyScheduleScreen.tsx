import { Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import type { MyScheduleOut, MyShiftOut } from '../../api/generated/model'
import { useMySchedule } from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { Section } from '../../components/ui/field'
import { EmptyState, ErrorState, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import {
  dayAndMonth,
  weekdayGenitive,
  hoursText,
  inMonth,
  monthGenitive,
  parseDate,
  relativeDay,
  shortTime,
  toIsoDate,
  weekdayLong,
  weekdayShort,
} from '../../lib/dates'
import { GiveAwaySheet } from './GiveAwaySheet'
import { differenceText } from './hours'
import { HoursSheet } from './HoursSheet'
import { OffersToTake } from './OffersToTake'
import { buildRows, coworkersText } from './rows'

export function MyScheduleScreen({
  companyId,
  readOnly = false,
  today: fixedTime,
}: {
  companyId: string
  readOnly?: boolean
  today?: Date
}) {
  const schedule = useMySchedule({ company_id: companyId })
  const [clock, setClock] = useState(() => new Date())
  const today = fixedTime ?? clock
  const shifts = (schedule.data?.data as MyScheduleOut | undefined)?.shifts
  useEffect(() => {
    if (fixedTime || !shifts?.length) return
    const now = Date.now()
    const boundaries = shifts
      .flatMap((s) => [Date.parse(counted(s).start_at), Date.parse(counted(s).end_at)])
      .filter((t) => t > now)
    const delay = Math.min(86_400_000, Math.min(...boundaries) - now + 1)
    const timer = window.setTimeout(() => setClock(new Date()), delay)
    return () => window.clearTimeout(timer)
  }, [fixedTime, shifts, clock])
  const [giving, setGiving] = useState<string | null>(null)
  const [reporting, setReporting] = useState<string | null>(null)

  if (schedule.isPending) return <Loading>Wczytuję Twój grafik…</Loading>
  if (schedule.isError) {
    return (
      <ErrorState onRetry={() => void schedule.refetch()}>
        {errorMessage(schedule.error, 'Nie udało się wczytać grafiku. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = schedule.data.data as MyScheduleOut
  const ahead = (shift: MyShiftOut) => Date.parse(counted(shift).end_at) > today.getTime()
  const [next, ...rest] = data.shifts.filter(ahead)
  // A shift that ended while the screen was open moves to "Minione zmiany" at once (newest first), so
  // "Zgłoś inne godziny" stays at hand right when the work ends.
  const known = new Set((data.recent ?? []).map((s) => s.id))
  const justEnded = data.shifts.filter((s) => !ahead(s) && s.can_report && !known.has(s.id)).reverse()
  const recent = [...justEnded, ...(data.recent ?? [])]
  const give = readOnly ? undefined : (shift: MyShiftOut) => setGiving(shift.id)
  const report = readOnly ? undefined : (shift: MyShiftOut) => setReporting(shift.id)
  // "Zgłoś inne godziny" at today's or the running shift; earlier ones are in "Minione zmiany".
  const reportNext =
    next && next.can_report && (next.date === toIsoDate(today) || Date.parse(next.start_at) <= today.getTime())
      ? report
      : undefined

  return (
    <div className="grid gap-5">
      <OffersToTake companyId={companyId} readOnly={readOnly} />
      {next ? (
        <NextShift
          shift={next}
          today={today}
          onGive={Date.parse(next.start_at) > today.getTime() ? give : undefined}
          onReport={reportNext}
        />
      ) : (
        <EmptyState title="Nie masz jeszcze zmian w grafiku">
          <p className="m-0">Gdy kierownik opublikuje grafik, zobaczysz tu swoje zmiany i godziny.</p>
          <p className="m-0">
            Do tego czasu możesz zaznaczyć,{' '}
            <Link to="/kiedy-moge" className="font-semibold text-accent underline underline-offset-4">
              kiedy możesz pracować
            </Link>
            .
          </p>
        </EmptyState>
      )}
      {next && (rest.length > 0 || (data.published_until ?? next.date) > next.date) && (
        <UpcomingList first={next} shifts={rest} publishedUntil={data.published_until} onGive={give} />
      )}
      {data.published_until && (
        <p className="m-0 text-ink-muted">
          Grafik jest opublikowany do {weekdayGenitive(parseDate(data.published_until))} {dayAndMonth(parseDate(data.published_until))}. Dalsze dni pokażemy, gdy kierownik
          opublikuje kolejny grafik.
        </p>
      )}
      <div className="grid gap-2">
        {data.months.map((month) => (
          <div
            key={month.month}
            className="flex items-center justify-between gap-3 rounded-md border-2 border-ink bg-surface px-4 py-3.5"
          >
            <span>Razem {inMonth(month.month)}</span>
            <b className="text-xl tabular-nums">{hoursText(month.hours)}</b>
          </div>
        ))}
      </div>
      {recent.length > 0 && <PastShifts shifts={recent} onReport={report} />}
      <GiveAwaySheet shift={data.shifts.find((s) => s.id === giving) ?? null} onClose={() => setGiving(null)} />
      <HoursSheet
        shift={[...data.shifts, ...recent].find((s) => s.id === reporting) ?? null}
        now={today}
        onClose={() => setReporting(null)}
      />
    </div>
  )
}

/** The hours that count: approved other hours, else the schedule's. */
function counted(shift: MyShiftOut) {
  return shift.worked ?? shift
}

function timeRange(shift: MyShiftOut): string {
  const hours = counted(shift)
  return `${shortTime(hours.start_time)}–${shortTime(hours.end_time)}`
}

/** Under a shift: the schedule's hours when others count, and my report waiting for the manager. */
function HoursNote({ shift }: { shift: MyShiftOut }) {
  if (!shift.worked && !shift.report) return null
  return (
    <div className="grid text-sm text-ink-muted">
      {shift.worked && (
        <span>
          W grafiku {shortTime(shift.start_time)}–{shortTime(shift.end_time)}, {differenceText(shift.worked.difference_minutes)}{' '}
          ({shift.worked.by_manager ? 'od kierownika' : 'zatwierdzone'})
        </span>
      )}
      {shift.report && (
        <span className="font-semibold text-prefer-not">
          Zgłoszone {shortTime(shift.report.start_time)}–{shortTime(shift.report.end_time)}: czeka na kierownika
        </span>
      )}
    </div>
  )
}

function shiftLine(shift: MyShiftOut): string {
  const kind = shift.shift_type_name ? `, ${shift.shift_type_name.toLowerCase()}` : ''
  return `${shift.position_name}${kind}`
}

/** The nearest shift, drawn like a page of a tear-off calendar: a big day number to read at arm's length. */
/** "Oddaj zmianę" next to a shift, or what happens to a shift I am giving away. */
function GiveButton({ shift, onGive, wide }: { shift: MyShiftOut; onGive?: (shift: MyShiftOut) => void; wide?: boolean }) {
  if (!onGive) return null
  const label = shift.offer_status
    ? shift.offer_status === 'claimed'
      ? 'Oddajesz: czeka na kierownika'
      : 'Oddajesz, jeszcze nikt się nie zgłosił'
    : wide
      ? 'Oddaj tę zmianę'
      : 'Oddaj'
  return (
    <Button
      variant={shift.offer_status ? 'secondary' : 'quiet'}
      size="normal"
      wide={wide}
      className={wide ? '' : 'px-2 text-sm'}
      onClick={() => onGive(shift)}
    >
      {label}
    </Button>
  )
}

function NextShift({
  shift,
  today,
  onGive,
  onReport,
}: {
  shift: MyShiftOut
  today: Date
  onGive?: (shift: MyShiftOut) => void
  onReport?: (shift: MyShiftOut) => void
}) {
  const day = parseDate(shift.date)
  return (
    <article aria-label="Najbliższa zmiana" className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex justify-between border-b-2 border-dashed border-accent-ink/55 bg-accent px-4 py-2 font-semibold text-accent-ink">
        <span>{Date.parse(shift.start_at) <= today.getTime() ? 'Trwa Twoja zmiana' : 'Najbliższa zmiana'}</span>
        <span>{relativeDay(day, today)}</span>
      </div>
      <div className="grid grid-cols-[auto_1fr] items-center gap-4 px-4 pt-3.5 pb-4.5">
        <div className="min-w-21 text-center">
          <b className="block text-hero font-extrabold tracking-tight text-accent tabular-nums">{day.getDate()}</b>
          <span className="text-sm font-semibold text-ink-muted">
            {weekdayLong(day)}
            <br />
            {monthGenitive(day)}
          </span>
        </div>
        <div className="grid min-w-0 gap-0.5">
          <div className="text-xl font-extrabold tabular-nums">{timeRange(shift)}</div>
          <HoursNote shift={shift} />
          <div className="font-semibold">{shiftLine(shift)}</div>
          <div className="text-sm text-ink-muted">
            {shift.location_name}
            {shift.away && ' (inny lokal)'}
          </div>
          <div className="text-sm text-ink-muted">
            {shift.coworkers.length > 0 ? `Z Tobą: ${coworkersText(shift.coworkers)}` : 'Na tej zmianie nie ma nikogo więcej.'}
          </div>
        </div>
      </div>
      {(onGive || onReport) && (
        <div className="grid gap-1 border-t border-grid px-4 py-2">
          <GiveButton shift={shift} onGive={onGive} wide />
          {onReport && (
            <Button variant="quiet" size="normal" wide onClick={() => onReport(shift)}>
              {shift.report ? 'Zgłoszone inne godziny: zmień albo wycofaj' : 'Zgłoś inne godziny'}
            </Button>
          )}
        </div>
      )}
    </article>
  )
}

function DateCell({ date }: { date: Date }) {
  return (
    <div className="text-center leading-tight">
      <b className="block text-xl font-extrabold tabular-nums">{date.getDate()}</b>
      <span className="text-xs font-semibold text-ink-muted">{weekdayShort(date)}</span>
    </div>
  )
}

function UpcomingList({
  first,
  shifts,
  publishedUntil,
  onGive,
}: {
  first: MyShiftOut
  shifts: MyShiftOut[]
  publishedUntil?: string | null
  onGive?: (shift: MyShiftOut) => void
}) {
  const rows = buildRows(first, shifts, publishedUntil)
  return (
    <section aria-labelledby="upcoming" className="grid gap-3">
      <h2 id="upcoming" className="m-0 text-lg font-extrabold">
        Kolejne dni
      </h2>
      <ol className="m-0 grid list-none overflow-hidden rounded-lg border border-line bg-surface p-0">
        {rows.map((row) =>
          row.kind === 'week' ? (
            <li key={row.key} className="border-t border-grid bg-paper px-4 py-1.5 text-xs font-semibold text-ink-muted">
              {row.label}
            </li>
          ) : row.kind === 'off' ? (
            <li key={row.key} className="grid grid-cols-[52px_1fr] items-center gap-3 border-t border-grid px-4 py-2 first:border-t-0">
              <DateCell date={row.date} />
              <span className="text-ink-muted">Wolne</span>
            </li>
          ) : (
            <li
              key={row.key}
              className={
                'grid items-center gap-x-3 gap-y-2 border-t border-grid px-4 py-3 first:border-t-0 ' +
                (row.shift.offer_status ? 'grid-cols-[52px_1fr]' : 'grid-cols-[52px_1fr_auto]')
              }
            >
              {row.showDate ? <DateCell date={parseDate(row.shift.date)} /> : <span />}
              <div className="min-w-0">
                <div className="font-extrabold tabular-nums">{timeRange(row.shift)}</div>
                <HoursNote shift={row.shift} />
                <div className="text-sm text-ink-muted">
                  {shiftLine(row.shift)}
                  {row.shift.away && `, ${row.shift.location_name}`}
                  {row.shift.coworkers.length > 0 && `. Z Tobą: ${coworkersText(row.shift.coworkers, 2)}`}
                </div>
              </div>
              {row.shift.offer_status ? (
                <div className="col-start-2">
                  <GiveButton shift={row.shift} onGive={onGive} />
                </div>
              ) : (
                <GiveButton shift={row.shift} onGive={onGive} />
              )}
            </li>
          ),
        )}
      </ol>
    </section>
  )
}

/** The last two weeks: the hours that counted, and "Inne godziny" while I may still report them. */
function PastShifts({ shifts, onReport }: { shifts: MyShiftOut[]; onReport?: (shift: MyShiftOut) => void }) {
  const waiting = shifts.filter((s) => s.report).length
  return (
    <Section
      collapsible
      title="Minione zmiany"
      status={waiting > 0 ? <span className="font-semibold text-prefer-not">czeka: {waiting}</span> : undefined}
      description="Ostatnie dwa tygodnie. Gdy praca trwała dłużej albo krócej niż w grafiku, zgłoś to kierownikowi."
    >
      <ol className="m-0 grid list-none overflow-hidden rounded-lg border border-line bg-surface p-0">
        {shifts.map((shift) => (
          <li
            key={shift.id}
            className="grid grid-cols-[52px_1fr_auto] items-center gap-x-3 border-t border-grid px-4 py-3 first:border-t-0"
          >
            <DateCell date={parseDate(shift.date)} />
            <div className="min-w-0">
              <div className="font-extrabold tabular-nums">{timeRange(shift)}</div>
              <HoursNote shift={shift} />
              <div className="text-sm text-ink-muted">
                {shiftLine(shift)}
                {shift.away && `, ${shift.location_name}`}
              </div>
            </div>
            {onReport && shift.can_report ? (
              <Button variant="quiet" size="normal" className="px-2 text-sm" onClick={() => onReport(shift)}>
                Inne godziny
              </Button>
            ) : (
              <span />
            )}
          </li>
        ))}
      </ol>
    </Section>
  )
}
