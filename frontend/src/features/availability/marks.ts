import type { AvailabilityDayOut, DayIn } from '../../api/generated/model'
import { compactTime } from '../../lib/dates'

/**
 * Three states: "nie mogę", "mogę" and "chętnie". "neutral" is "mogę", the state of every day until the employee
 * changes it (shown in light green, never as an empty day). Wishes like "wolę nie" are written as a text request.
 */
export type AvailabilityState = 'cannot' | 'neutral' | 'prefer'

export const STATES: AvailabilityState[] = ['cannot', 'neutral', 'prefer']

export const STATE_LABEL: Record<AvailabilityState, string> = {
  cannot: 'Nie mogę',
  neutral: 'Mogę',
  prefer: 'Chętnie',
}

/**
 * One day as the employee marked it. Hours are "HH:MM"; an end at or before the start means the next morning.
 * An optional second window ("6–10 lub 16–22"); `oneShift` ("albo") = at most one shift that day.
 */
export type Mark = {
  state: AvailabilityState
  from: string | null
  to: string | null
  from2?: string | null
  to2?: string | null
  oneShift?: boolean
}

export const NEUTRAL: Mark = { state: 'neutral', from: null, to: null }

export type Marks = Record<string, Mark>

const hhmm = (value: string | null | undefined) => (value ? value.slice(0, 5) : null)

export function marksFromServer(days: AvailabilityDayOut[]): Marks {
  const marks: Marks = {}
  for (const day of days) {
    marks[day.date] = {
      state: day.state,
      from: hhmm(day.from_time),
      to: hhmm(day.to_time),
      from2: hhmm(day.from_time_2),
      to2: hhmm(day.to_time_2),
      oneShift: Boolean(day.one_shift),
    }
  }
  return marks
}

export const markOf = (marks: Marks, date: string): Mark => marks[date] ?? NEUTRAL

export function sameMark(a: Mark, b: Mark): boolean {
  return (
    a.state === b.state &&
    a.from === b.from &&
    a.to === b.to &&
    (a.from2 ?? null) === (b.from2 ?? null) &&
    (a.to2 ?? null) === (b.to2 ?? null) &&
    Boolean(a.oneShift) === Boolean(b.oneShift)
  )
}

export function toDayIn(date: string, mark: Mark): DayIn {
  const day: DayIn = { date, state: mark.state, from_time: mark.from, to_time: mark.to }
  if (!hasSecondWindow(mark)) return day // the server clears a second window that is not sent
  return { ...day, from_time_2: mark.from2, to_time_2: mark.to2, one_shift: Boolean(mark.oneShift) }
}

export function hasSecondWindow(mark: Mark): boolean {
  return Boolean(mark.from2 && mark.to2)
}

export function hasHours(mark: Mark): boolean {
  return mark.from !== null || mark.to !== null
}

/** True when the hours run past midnight into the next morning (an end at 0:00 is midnight, not a night). */
export function overnight(mark: Mark): boolean {
  return mark.from !== null && mark.to !== null && mark.to !== '00:00' && mark.to <= mark.from
}

/** One window in words: "14:00–22:00", "do 9:00" (from midnight), "od 11:00" (to midnight). */
export function windowWords(from: string | null, to: string | null, time: (value: string) => string): string {
  if (from === null || from === '00:00') return to === null || to === '00:00' ? '' : `do ${time(to)}`
  if (to === null || to === '00:00') return `od ${time(from)}`
  return `${time(from)}–${time(to)}`
}

/** Short label inside a calendar cell: "14–22", "od 14", "do 12", "6–10/16–22", "do 9/od 11". */
export function cellHours(mark: Mark): string | null {
  if (!hasHours(mark)) return null
  const first = windowWords(mark.from, mark.to, compactTime)
  return hasSecondWindow(mark) ? `${first}/${windowWords(mark.from2!, mark.to2!, compactTime)}` : first
}

/** Spoken description, e.g. "chętnie, tylko 14:00–22:00", "mogę, tylko do 9:00 lub od 11:00". "Nie mogę" has no
 * hours: it is always the whole day. */
export function describeMark(mark: Mark): string {
  const state = STATE_LABEL[mark.state].toLowerCase()
  if (!hasHours(mark) || mark.state === 'cannot') return state
  const plain = (value: string) => value
  let window = `${windowWords(mark.from, mark.to, plain)}${overnight(mark) ? ' (do rana)' : ''}`
  if (hasSecondWindow(mark)) {
    const night = mark.to2 !== '00:00' && mark.to2! <= mark.from2!
    const second = `${windowWords(mark.from2!, mark.to2!, plain)}${night ? ' (do rana)' : ''}`
    window = mark.oneShift ? `${window} albo ${second} (jedna zmiana)` : `${window} lub ${second}`
  }
  return `${state}, tylko ${window}`
}

export function countStates(marks: Marks, dates: string[]): Record<AvailabilityState, number> {
  const counts: Record<AvailabilityState, number> = { cannot: 0, neutral: 0, prefer: 0 }
  for (const date of dates) counts[markOf(marks, date).state] += 1
  return counts
}
