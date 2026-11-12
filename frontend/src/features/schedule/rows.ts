import type { MyShiftOut } from '../../api/generated/model'
import { addDays, dayAndMonth, parseDate, toIsoDate, weekdayIndex } from '../../lib/dates'

export type Row =
  | { kind: 'week'; key: string; label: string }
  | { kind: 'shift'; key: string; shift: MyShiftOut; showDate: boolean }
  | { kind: 'off'; key: string; date: Date }

/** All days from the first to the last shift: shifts, days off, and a line at each new week. */
export function buildRows(first: MyShiftOut, shifts: MyShiftOut[]): Row[] {
  const rows: Row[] = []
  const byDate = new Map<string, MyShiftOut[]>()
  for (const shift of shifts) byDate.set(shift.date, [...(byDate.get(shift.date) ?? []), shift])
  const last = parseDate(shifts[shifts.length - 1].date)
  let day = addDays(parseDate(first.date), 1)
  const firstOfList = day
  while (day <= last) {
    const iso = toIsoDate(day)
    if (weekdayIndex(day) === 0 && day > firstOfList) {
      const sunday = addDays(day, 6)
      rows.push({ kind: 'week', key: `w-${iso}`, label: weekLabel(day, sunday) })
    }
    const todays = byDate.get(iso)
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
