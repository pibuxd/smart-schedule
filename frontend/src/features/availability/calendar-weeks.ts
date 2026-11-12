import { addDays, parseDate, toIsoDate, weekdayIndex } from '../../lib/dates'

/** Monday-first weeks covering the period; `null` = a day outside the period. */
export function calendarWeeks(start: string, end: string): (string | null)[][] {
  const first = parseDate(start)
  const last = parseDate(end)
  const weeks: (string | null)[][] = []
  let day = addDays(first, -weekdayIndex(first))
  while (day <= last) {
    const week: (string | null)[] = []
    for (let i = 0; i < 7; i++) {
      week.push(day >= first && day <= last ? toIsoDate(day) : null)
      day = addDays(day, 1)
    }
    weeks.push(week)
  }
  return weeks
}
