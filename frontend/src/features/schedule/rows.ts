import type { DaysOut, MyShiftOut } from '../../api/generated/model'
import { addDays, dayAndMonth, parseDate, toIsoDate, weekdayIndex } from '../../lib/dates'

export type Row =
  | { kind: 'week'; key: string; label: string }
  | { kind: 'shift'; key: string; shift: MyShiftOut; showDate: boolean }
  | { kind: 'off'; key: string; date: Date }
  | { kind: 'unpublished'; key: string; from: Date; to: Date }

/**
 * All days after the first shift up to the end of the published schedule (or the last shift, if later):
 * shifts, days off, and a line at each new week. A free last day of the month is shown too. A day without a shift
 * is a day off only inside a published schedule (`published`); a run of days outside them is one line saying the
 * schedule is not out yet (tests of PR #82, 26.11.2026).
 */
export function buildRows(
  first: MyShiftOut,
  shifts: MyShiftOut[],
  publishedUntil?: string | null,
  published?: DaysOut[],
): Row[] {
  const rows: Row[] = []
  const byDate = new Map<string, MyShiftOut[]>()
  for (const shift of shifts) byDate.set(shift.date, [...(byDate.get(shift.date) ?? []), shift])
  const lastShift = parseDate((shifts[shifts.length - 1] ?? first).date)
  const until = publishedUntil ? parseDate(publishedUntil) : lastShift
  const last = until > lastShift ? until : lastShift
  const isPublished = (iso: string) => !published || published.some((span) => span.start <= iso && iso <= span.end)
  const mondayOf = (date: Date) => toIsoDate(addDays(date, -weekdayIndex(date)))
  let week = mondayOf(parseDate(first.date))
  let gap: Extract<Row, { kind: 'unpublished' }> | null = null
  let day = addDays(parseDate(first.date), 1)
  while (day <= last) {
    const iso = toIsoDate(day)
    const todays = byDate.get(iso)
    if (!todays && !isPublished(iso)) {
      if (gap) gap.to = day
      else {
        gap = { kind: 'unpublished', key: `u-${iso}`, from: day, to: day }
        rows.push(gap)
      }
      day = addDays(day, 1)
      continue
    }
    gap = null
    if (mondayOf(day) !== week) {
      week = mondayOf(day)
      rows.push({ kind: 'week', key: `w-${iso}`, label: weekLabel(parseDate(week), addDays(parseDate(week), 6)) })
    }
    if (todays) todays.forEach((shift, i) => rows.push({ kind: 'shift', key: shift.id, shift, showDate: i === 0 }))
    else if (iso !== first.date) rows.push({ kind: 'off', key: `o-${iso}`, date: day })
    day = addDays(day, 1)
  }
  return rows
}

function weekLabel(monday: Date, sunday: Date): string {
  if (monday.getMonth() === sunday.getMonth()) return `Tydzień ${monday.getDate()}–${dayAndMonth(sunday)}`
  return `Tydzień ${dayAndMonth(monday)} – ${dayAndMonth(sunday)}`
}

/** "Anna Wróbel, Marek Zając i 4 inne osoby": a few names are enough to know who is around. */
export function coworkersText(names: string[], shown = 3): string {
  if (names.length <= shown + 1) return names.join(', ')
  const rest = names.length - shown
  const few = rest % 10 >= 2 && rest % 10 <= 4 && (rest % 100 < 12 || rest % 100 > 14)
  const people = few ? 'inne osoby' : 'innych osób'
  return `${names.slice(0, shown).join(', ')} i ${rest} ${people}`
}
