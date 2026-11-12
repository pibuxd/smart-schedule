import type { AvailabilityDayOut, DayIn } from '../../api/generated/model'
import { compactTime } from '../../lib/dates'

export type AvailabilityState = 'cannot' | 'prefer_not' | 'neutral' | 'prefer'

export const STATES: AvailabilityState[] = ['cannot', 'prefer_not', 'neutral', 'prefer']

export const STATE_LABEL: Record<AvailabilityState, string> = {
  cannot: 'Nie mogę',
  prefer_not: 'Wolę nie',
  neutral: 'Obojętnie',
  prefer: 'Chętnie',
}

/** One day as the employee marked it. Hours are "HH:MM"; an end at or before the start means the next morning. */
export type Mark = { state: AvailabilityState; from: string | null; to: string | null }

export const NEUTRAL: Mark = { state: 'neutral', from: null, to: null }

export type Marks = Record<string, Mark>

const hhmm = (value: string | null | undefined) => (value ? value.slice(0, 5) : null)

export function marksFromServer(days: AvailabilityDayOut[]): Marks {
  const marks: Marks = {}
  for (const day of days) marks[day.date] = { state: day.state, from: hhmm(day.from_time), to: hhmm(day.to_time) }
  return marks
}

export const markOf = (marks: Marks, date: string): Mark => marks[date] ?? NEUTRAL

export function sameMark(a: Mark, b: Mark): boolean {
  return a.state === b.state && a.from === b.from && a.to === b.to
}

export function toDayIn(date: string, mark: Mark): DayIn {
  return { date, state: mark.state, from_time: mark.from, to_time: mark.to }
}

/** Previous marks of the days that differ between two versions (for "Cofnij"). */
export function changedDays(before: Marks, after: Marks): Marks {
  const dates = new Set([...Object.keys(before), ...Object.keys(after)])
  const previous: Marks = {}
  for (const date of dates) {
    if (!sameMark(markOf(before, date), markOf(after, date))) previous[date] = markOf(before, date)
  }
  return previous
}

export function hasHours(mark: Mark): boolean {
  return mark.from !== null || mark.to !== null
}

/** True when the hours run past midnight into the next morning. */
export function overnight(mark: Mark): boolean {
  return mark.from !== null && mark.to !== null && mark.to <= mark.from
}

/** Short label inside a calendar cell: "14–22", "od 14", "do 12". */
export function cellHours(mark: Mark): string | null {
  if (mark.from && mark.to) return `${compactTime(mark.from)}–${compactTime(mark.to)}`
  if (mark.from) return `od ${compactTime(mark.from)}`
  if (mark.to) return `do ${compactTime(mark.to)}`
  return null
}

/** Spoken description, e.g. "chętnie, tylko 14:00–22:00". */
export function describeMark(mark: Mark): string {
  const state = STATE_LABEL[mark.state].toLowerCase()
  if (!hasHours(mark)) return state
  const window = `${mark.from ?? '0:00'}–${mark.to ?? '24:00'}${overnight(mark) ? ' (do rana)' : ''}`
  return mark.state === 'cannot' || mark.state === 'prefer_not' ? `${state} w godzinach ${window}` : `${state}, tylko ${window}`
}

export function countStates(marks: Marks, dates: string[]): Record<AvailabilityState, number> {
  const counts: Record<AvailabilityState, number> = { cannot: 0, prefer_not: 0, neutral: 0, prefer: 0 }
  for (const date of dates) counts[markOf(marks, date).state] += 1
  return counts
}

/** Days among `dates` that already carry a mark and would end up different (for the overwrite note). */
export function marksToReplace(marks: Marks, dates: string[], next?: Mark): number {
  return dates.filter((date) => {
    const mark = markOf(marks, date)
    const marked = mark.state !== 'neutral' || hasHours(mark)
    return marked && (next === undefined || !sameMark(mark, next))
  }).length
}

/** "Zastąpi 3 zaznaczone dni w tym miesiącu." or null when nothing is replaced. */
export function replaceNote(count: number): string | null {
  if (count === 0) return null
  const tens = count % 100
  const few = count % 10 >= 2 && count % 10 <= 4 && (tens < 12 || tens > 14)
  const words = count === 1 ? 'zaznaczony dzień' : few ? 'zaznaczone dni' : 'zaznaczonych dni'
  return `Zastąpi ${count} ${words} w tym miesiącu.`
}
