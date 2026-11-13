// Polish date words, written out so they read naturally ("w grudniu", "4 grudnia", "pt").

const WEEKDAYS_SHORT = ['pon', 'wt', 'śr', 'czw', 'pt', 'sob', 'niedz']
const WEEKDAYS_LONG = ['poniedziałek', 'wtorek', 'środa', 'czwartek', 'piątek', 'sobota', 'niedziela']
const WEEKDAYS_GENITIVE = ['poniedziałku', 'wtorku', 'środy', 'czwartku', 'piątku', 'soboty', 'niedzieli']
const MONTHS_GENITIVE = [
  'stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca',
  'lipca', 'sierpnia', 'września', 'października', 'listopada', 'grudnia',
]
const MONTHS_LOCATIVE = [
  'styczniu', 'lutym', 'marcu', 'kwietniu', 'maju', 'czerwcu',
  'lipcu', 'sierpniu', 'wrześniu', 'październiku', 'listopadzie', 'grudniu',
]
const MONTHS_NOMINATIVE = [
  'styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec',
  'lipiec', 'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień',
]
export const WEEKDAY_HEADERS = WEEKDAYS_SHORT

/** "2026-12" -> "Grudzień 2026" */
export function monthName(month: string): string {
  const name = MONTHS_NOMINATIVE[Number(month.slice(5, 7)) - 1]
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${month.slice(0, 4)}`
}

/** "2026-12-04" -> a local Date at midnight (no time-zone shifts). */
export function parseDate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function toIsoDate(date: Date): string {
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${m}-${d}`
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days)
}

/** Monday = 0 … Sunday = 6. */
export function weekdayIndex(date: Date): number {
  return (date.getDay() + 6) % 7
}

export const weekdayShort = (date: Date) => WEEKDAYS_SHORT[weekdayIndex(date)]
export const weekdayLong = (date: Date) => WEEKDAYS_LONG[weekdayIndex(date)]
/** "do wtorku": the weekday after "do". */
export const weekdayGenitive = (date: Date) => WEEKDAYS_GENITIVE[weekdayIndex(date)]
export const monthGenitive = (date: Date) => MONTHS_GENITIVE[date.getMonth()]
export const monthLocative = (date: Date) => MONTHS_LOCATIVE[date.getMonth()]

/** "piątek 4 grudnia" */
export function dayTitle(date: Date): string {
  return `${weekdayLong(date)} ${date.getDate()} ${monthGenitive(date)}`
}

/** "4 grudnia" */
export function dayAndMonth(date: Date): string {
  return `${date.getDate()} ${monthGenitive(date)}`
}

/** "dzisiaj", "jutro", "pojutrze", "za 5 dni" */
export function relativeDay(date: Date, today: Date): string {
  const days = Math.round((parseDate(toIsoDate(date)).getTime() - parseDate(toIsoDate(today)).getTime()) / 86_400_000)
  if (days <= 0) return 'dzisiaj'
  if (days === 1) return 'jutro'
  if (days === 2) return 'pojutrze'
  return `za ${days} dni`
}

/** "06:00" or "06:00:00" -> "6:00" */
export function shortTime(value: string): string {
  const [h, m] = value.split(':')
  return `${Number(h)}:${m}`
}

/** "14:00" -> "14", "14:30" -> "14:30" (for small labels inside calendar cells). */
export function compactTime(value: string): string {
  const [h, m] = value.split(':')
  return m === '00' ? String(Number(h)) : `${Number(h)}:${m}`
}

/** 112 -> "112 godz.", 7.5 -> "7,5 godz." */
export function hoursText(hours: number): string {
  const rounded = Math.round(hours * 10) / 10
  return `${String(rounded).replace('.', ',')} godz.`
}

/** "2026-11" -> "w listopadzie" */
export function inMonth(month: string): string {
  return `w ${MONTHS_LOCATIVE[Number(month.slice(5, 7)) - 1]}`
}

/** Title of a period: "w grudniu" for a whole month, otherwise "7–13 grudnia". */
export function periodWords(startIso: string, endIso: string): string {
  const start = parseDate(startIso)
  const end = parseDate(endIso)
  const wholeMonth =
    start.getDate() === 1 && addDays(end, 1).getDate() === 1 && start.getMonth() === end.getMonth()
  if (wholeMonth) return `w ${monthLocative(start)}`
  if (start.getMonth() === end.getMonth()) return `${start.getDate()}–${end.getDate()} ${monthGenitive(end)}`
  return `${dayAndMonth(start)} – ${dayAndMonth(end)}`
}
