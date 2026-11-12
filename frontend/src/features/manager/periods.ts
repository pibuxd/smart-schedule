import type { LocationOut, LocationSummaryOut, PeriodOut } from '../../api/generated/model'
import { addDays, parseDate, toIsoDate } from '../../lib/dates'
import type { ArrangeTarget } from './ArrangeSchedule'
import { daysUntil } from './words'

/** The period the manager most likely wants: the current or next one, else the latest. */
export function pickPeriod(periods: PeriodOut[], today: Date): PeriodOut | undefined {
  const iso = toIsoDate(today)
  const upcoming = periods.filter((p) => p.end >= iso).sort((a, b) => a.start.localeCompare(b.start))
  return upcoming[0] ?? [...periods].sort((a, b) => b.start.localeCompare(a.start))[0]
}

/** Dates for a new period: right after the last one, a month or a week long as the location is set up. */
export function nextPeriodDates(location: LocationOut, periods: PeriodOut[], today: Date) {
  const last = [...periods].sort((a, b) => b.end.localeCompare(a.end))[0]
  let start = last ? addDays(parseDate(last.end), 1) : addDays(today, 1)
  let end: Date
  if (location.schedule_period === 'week') {
    if (!last) start = addDays(start, (7 - ((start.getDay() + 6) % 7)) % 7) // next Monday
    end = addDays(start, 6)
  } else {
    if (!last) start = new Date(start.getFullYear(), start.getMonth() + 1, 1)
    end = new Date(start.getFullYear(), start.getMonth() + 1, 0)
  }
  const deadline = addDays(start, -location.availability_deadline_days)
  return { start: toIsoDate(start), end: toIsoDate(end), deadline: toIsoDate(deadline) }
}

/** What the "Ułóż grafik" sheet needs to know about a location from the overview. */
export function arrangeTarget(location: LocationSummaryOut, today: Date): ArrangeTarget {
  const period = location.period!
  return {
    periodId: period.id,
    locationId: location.id,
    locationName: location.name,
    missing: period.missing.length,
    deadlinePassed: daysUntil(period.deadline, today) < 0,
    manualChanges: period.manual_changes,
    hasVersion: period.latest_version_id !== null,
  }
}
