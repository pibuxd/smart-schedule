import { useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Lock, Minus, PenLine, Plus } from 'lucide-react'
import { useState } from 'react'

import type { ClosureOut, LocationSetupOut, ShiftTypeOut, StaffingExceptionOut } from '../../api/generated/model'
import { useCreateClosure, useDeleteClosure, useSaveDayStaffing } from '../../api/generated/staffing/staffing'
import { Button } from '../../components/ui/button'
import { Section, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import { dayTitle, monthName, parseDate, shortTime, toIsoDate, WEEKDAY_HEADERS, weekdayIndex } from '../../lib/dates'
import { calendarWeeks } from '../availability/calendar-weeks'
import { useManager } from './ManagerContext'

type Cell = { count: number; experienced: number; start: string; end: string }
const pairKey = (shiftTypeId: string, positionId: string) => `${shiftTypeId}|${positionId}`
const hhmm = (value: string | null | undefined) => (value ? value.slice(0, 5) : '')

/** What a date needs for every shift and position: the weekday's staffing with the date's own changes on top. */
function dayCells(setup: LocationSetupOut, date: string): { usual: Record<string, Cell>; now: Record<string, Cell> } {
  const weekday = weekdayIndex(parseDate(date))
  const usual: Record<string, Cell> = {}
  for (const c of setup.staffing) {
    if (c.weekday !== weekday) continue
    usual[pairKey(c.shift_type_id, c.position_id)] = { count: c.count, experienced: c.experienced, start: '', end: '' }
  }
  const now = { ...usual }
  for (const e of setup.exceptions) {
    if (e.date !== date) continue
    now[pairKey(e.shift_type_id, e.position_id)] = {
      count: e.count, experienced: e.experienced, start: hhmm(e.start_time), end: hhmm(e.end_time),
    }
  }
  return { usual, now }
}

const people = (cells: Record<string, Cell>) => Object.values(cells).reduce((sum, c) => sum + c.count, 0)

/**
 * A month of the location: every day shows how many people it needs. Choosing a day opens its staffing, where the
 * manager sets other numbers than the weekday usually has (or closes the location for the day).
 */
export function StaffingCalendar({ locationId, setup, today = new Date() }: { locationId: string; setup: LocationSetupOut; today?: Date }) {
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  if (setup.shift_types.length === 0 || setup.positions.length === 0) return null

  const first = new Date(today.getFullYear(), today.getMonth() + offset, 1)
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0)
  const todayIso = toIsoDate(today)
  const changed = new Set(setup.exceptions.map((e) => e.date))
  const closed = new Map(setup.closures.map((c) => [c.date, c]))

  return (
    <Section title="Obsada w wybrane dni" description="Wybierz dzień, żeby ustawić w nim inną obsadę niż zwykle, np. w Wigilię.">
      <div className="grid gap-2 rounded-md border border-line bg-surface p-3">
        <div className="flex items-center justify-between gap-2">
          <Button variant="quiet" size="normal" aria-label="Poprzedni miesiąc" disabled={offset === 0} onClick={() => setOffset(offset - 1)}>
            <ChevronLeft aria-hidden="true" size={22} />
          </Button>
          <h3 className="m-0 text-lg font-extrabold" aria-live="polite">{monthName(toIsoDate(first))}</h3>
          <Button variant="quiet" size="normal" aria-label="Następny miesiąc" disabled={offset >= 24} onClick={() => setOffset(offset + 1)}>
            <ChevronRight aria-hidden="true" size={22} />
          </Button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center text-xs font-semibold text-ink-muted" aria-hidden="true">
          {WEEKDAY_HEADERS.map((day) => <span key={day}>{day}</span>)}
        </div>
        {calendarWeeks(toIsoDate(first), toIsoDate(last)).map((week, i) => (
          <div key={i} className="grid grid-cols-7 gap-1">
            {week.map((date, j) => {
              if (!date) return <span key={j} />
              const closure = closed.get(date)
              const other = changed.has(date)
              const total = people(dayCells(setup, date).now)
              const words = closure ? 'lokal zamknięty' : `${total} os.${other ? ', inaczej niż zwykle' : ''}`
              return (
                <button
                  key={date}
                  type="button"
                  disabled={date < todayIso}
                  aria-label={`${dayTitle(parseDate(date))}: ${words}`}
                  onClick={() => setOpen(date)}
                  className={cn(
                    'grid min-h-(--touch-main) cursor-pointer content-center justify-items-center rounded-sm border-2 px-0.5',
                    'hover:border-accent disabled:cursor-not-allowed disabled:opacity-50',
                    closure ? 'border-dashed border-line bg-paper text-ink-muted' : other ? 'border-accent bg-accent-soft' : 'border-line bg-surface',
                  )}
                >
                  <span className="text-xs text-ink-muted">{parseDate(date).getDate()}</span>
                  <span className="flex items-center gap-0.5 text-sm font-semibold">
                    {closure ? <Lock aria-hidden="true" size={16} /> : <>{other && <PenLine aria-hidden="true" size={14} className="text-accent" />}{total}</>}
                  </span>
                </button>
              )
            })}
          </div>
        ))}
        <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-sm text-ink-muted">
          <li>Liczba: ile osób potrzeba</li>
          <li className="flex items-center gap-1.5"><PenLine aria-hidden="true" size={16} className="text-accent" /> inaczej niż zwykle</li>
          <li className="flex items-center gap-1.5"><Lock aria-hidden="true" size={16} /> lokal zamknięty</li>
        </ul>
      </div>
      <Sheet
        open={open !== null}
        onOpenChange={(o) => !o && setOpen(null)}
        title={open ? dayTitle(parseDate(open)) : ''}
        description="Obsada tylko tego dnia. Działa w grafikach, które ułożysz od teraz."
      >
        {open && (
          <DayForm key={open} locationId={locationId} setup={setup} date={open} closure={closed.get(open)}
            exceptions={setup.exceptions.filter((e) => e.date === open)} onDone={() => setOpen(null)} />
        )}
      </Sheet>
    </Section>
  )
}

function usualHours(st: ShiftTypeOut): string {
  return st.start_time && st.end_time ? `${shortTime(hhmm(st.start_time))}–${shortTime(hhmm(st.end_time))}` : 'dowolne godziny'
}

function DayForm({ locationId, setup, date, closure, exceptions, onDone }: {
  locationId: string
  setup: LocationSetupOut
  date: string
  closure: ClosureOut | undefined
  exceptions: StaffingExceptionOut[]
  onDone: () => void
}) {
  const { readOnly } = useManager()
  const save = useSaveDayStaffing()
  const close = useCreateClosure()
  const reopen = useDeleteClosure()
  const queryClient = useQueryClient()
  const [{ usual, now }] = useState(() => dayCells(setup, date))
  const [cells, setCells] = useState(now)
  const [note, setNote] = useState(exceptions.find((e) => e.note)?.note ?? '')
  const busy = save.isPending || close.isPending || reopen.isPending
  const done = { onSuccess: () => { void queryClient.invalidateQueries(); onDone() } }
  const error = save.error ?? close.error ?? reopen.error

  if (closure) {
    return (
      <div className="grid gap-4">
        <p className="m-0">Lokal jest tego dnia zamknięty{closure.note ? ` (${closure.note})` : ''}. Nikt nie dostanie zmiany.</p>
        {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
        <Button variant="secondary" wide disabled={busy || readOnly} onClick={() => reopen.mutate({ closureId: closure.id }, done)}>
          Otwórz lokal w ten dzień
        </Button>
      </div>
    )
  }

  const set = (key: string, change: Partial<Cell>) =>
    setCells((all) => ({ ...all, [key]: { ...(all[key] ?? { count: 0, experienced: 0, start: '', end: '' }), ...change } }))
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const sent = setup.shift_types.flatMap((st) => setup.positions.map((pos) => {
      const cell = cells[pairKey(st.id, pos.id)]
      return {
        shift_type_id: st.id, position_id: pos.id, count: cell?.count ?? 0,
        experienced: Math.min(cell?.experienced ?? 0, cell?.count ?? 0),
        start_time: cell?.start || null, end_time: cell?.end || null,
      }
    }))
    save.mutate({ locationId, day: date, data: { cells: sent, note } }, done)
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      {setup.shift_types.map((st) => (
        <fieldset key={st.id} disabled={readOnly || busy} className="m-0 grid gap-2 rounded-md border border-line bg-surface p-3">
          <legend className="px-1 font-bold">{st.name} <span className="font-normal text-ink-muted">({usualHours(st)})</span></legend>
          {setup.positions.map((pos) => {
            const key = pairKey(st.id, pos.id)
            const cell = cells[key] ?? { count: 0, experienced: 0, start: '', end: '' }
            const name = `${st.name}, ${pos.name}`
            return (
              <div key={pos.id} className="grid gap-1 border-t border-grid pt-2 first:border-t-0 first:pt-0">
                <div className="flex items-center justify-between gap-3">
                  <span className="grid">
                    <span className="font-semibold">{pos.name}</span>
                    <span className="text-sm text-ink-muted">zwykle {usual[key]?.count ?? 0}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <StepButton label={`Mniej osób: ${name}`} disabled={cell.count <= 0} onClick={() => set(key, { count: cell.count - 1 })}>
                      <Minus aria-hidden="true" size={20} />
                    </StepButton>
                    <input
                      type="number" inputMode="numeric" min={0} max={50} aria-label={`Osoby: ${name}`} value={cell.count}
                      onChange={(e) => set(key, { count: Math.max(0, Math.min(50, Number(e.target.value) || 0)) })}
                      className="min-h-(--touch) w-14 rounded-sm border-2 border-line bg-surface text-center text-base font-semibold focus:border-accent"
                    />
                    <StepButton label={`Więcej osób: ${name}`} disabled={cell.count >= 50} onClick={() => set(key, { count: cell.count + 1 })}>
                      <Plus aria-hidden="true" size={20} />
                    </StepButton>
                  </span>
                </div>
                {cell.count > 0 && (
                  <details open={cell.experienced > 0 || cell.start !== '' || (st.kind === 'flexible' && !st.start_time)}>
                    <summary className="min-h-(--touch) cursor-pointer content-center text-sm font-semibold text-accent">Doświadczeni i inne godziny</summary>
                    <div className="grid grid-cols-3 gap-2">
                      <TextField label="Doświadczeni" aria-label={`W tym doświadczonych: ${name}`} type="number" inputMode="numeric" min={0} max={cell.count}
                        value={Math.min(cell.experienced, cell.count)} onChange={(e) => set(key, { experienced: Number(e.target.value) || 0 })} />
                      <TextField label="Od" aria-label={`Od: ${name}`} type="time" value={cell.start} onChange={(e) => set(key, { start: e.target.value })} />
                      <TextField label="Do" aria-label={`Do: ${name}`} type="time" value={cell.end} onChange={(e) => set(key, { end: e.target.value })} />
                    </div>
                  </details>
                )}
              </div>
            )
          })}
        </fieldset>
      ))}
      <TextField label="Powód (nieobowiązkowo)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="np. Wigilia" />
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={busy || readOnly}>Zapisz obsadę dnia</Button>
      {exceptions.length > 0 && (
        <Button variant="secondary" size="normal" wide disabled={busy || readOnly} onClick={() => save.mutate({ locationId, day: date, data: { cells: [], note: '' } }, done)}>
          Wróć do zwykłej obsady
        </Button>
      )}
      <Button variant="quiet" size="normal" wide disabled={busy || readOnly} onClick={() => close.mutate({ locationId, data: { date, note } }, done)}>
        Zamknij lokal w ten dzień
      </Button>
    </form>
  )
}

function StepButton({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button" aria-label={label} disabled={disabled} onClick={onClick}
      className="inline-flex min-h-(--touch) min-w-(--touch) cursor-pointer items-center justify-center rounded-sm border-2 border-accent bg-surface text-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  )
}
