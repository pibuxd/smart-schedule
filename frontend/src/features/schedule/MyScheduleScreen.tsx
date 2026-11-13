import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import type { MyScheduleOut, MyShiftOut } from '../../api/generated/model'
import { useMySchedule } from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { EmptyState, ErrorState, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import {
  hoursText,
  inMonth,
  monthGenitive,
  parseDate,
  relativeDay,
  shortTime,
  weekdayLong,
  weekdayShort,
} from '../../lib/dates'
import { GiveAwaySheet } from './GiveAwaySheet'
import { OffersToTake } from './OffersToTake'
import { buildRows, coworkersText } from './rows'

export function MyScheduleScreen({
  companyId,
  readOnly = false,
  today = new Date(),
}: {
  companyId: string
  readOnly?: boolean
  today?: Date
}) {
  const schedule = useMySchedule({ company_id: companyId })
  const [giving, setGiving] = useState<string | null>(null)

  if (schedule.isPending) return <Loading>Wczytuję Twój grafik…</Loading>
  if (schedule.isError) {
    return (
      <ErrorState onRetry={() => void schedule.refetch()}>
        {errorMessage(schedule.error, 'Nie udało się wczytać grafiku. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = schedule.data.data as MyScheduleOut
  const [next, ...rest] = data.shifts
  const give = readOnly ? undefined : (shift: MyShiftOut) => setGiving(shift.id)

  return (
    <div className="grid gap-5">
      <OffersToTake companyId={companyId} readOnly={readOnly} />
      {next ? (
        <NextShift shift={next} today={today} onGive={give} />
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
      {next && rest.length > 0 && <UpcomingList first={next} shifts={rest} onGive={give} />}
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
      <GiveAwaySheet shift={data.shifts.find((s) => s.id === giving) ?? null} onClose={() => setGiving(null)} />
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
      : 'Oddajesz: czeka na chętnego'
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
}: {
  shift: MyShiftOut
  today: Date
  onGive?: (shift: MyShiftOut) => void
}) {
  const day = parseDate(shift.date)
  return (
    <article aria-label="Najbliższa zmiana" className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex justify-between border-b-2 border-dashed border-accent-ink/55 bg-accent px-4 py-2 font-semibold text-accent-ink">
        <span>Najbliższa zmiana</span>
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
          <div className="text-xl font-extrabold tabular-nums">
            {shortTime(shift.start_time)}–{shortTime(shift.end_time)}
          </div>
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
      {onGive && (
        <div className="border-t border-grid px-4 py-2">
          <GiveButton shift={shift} onGive={onGive} wide />
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
  onGive,
}: {
  first: MyShiftOut
  shifts: MyShiftOut[]
  onGive?: (shift: MyShiftOut) => void
}) {
  const rows = buildRows(first, shifts)
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
              className="grid grid-cols-[52px_1fr_auto] items-center gap-3 border-t border-grid px-4 py-3 first:border-t-0"
            >
              {row.showDate ? <DateCell date={parseDate(row.shift.date)} /> : <span />}
              <div className="min-w-0">
                <div className="font-extrabold tabular-nums">
                  {shortTime(row.shift.start_time)}–{shortTime(row.shift.end_time)}
                </div>
                <div className="text-sm text-ink-muted">
                  {shiftLine(row.shift)}
                  {row.shift.away && `, ${row.shift.location_name}`}
                  {row.shift.coworkers.length > 0 && `. Z Tobą: ${coworkersText(row.shift.coworkers, 2)}`}
                </div>
              </div>
              <GiveButton shift={row.shift} onGive={onGive} />
            </li>
          ),
        )}
      </ol>
    </section>
  )
}
