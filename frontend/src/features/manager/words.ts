import type { SubscriptionOut } from '../../api/generated/model'
import { dayAndMonth, parseDate, periodWords, toIsoDate, weekdayShort } from '../../lib/dates'

export const PERIOD_STATUS: Record<string, string> = {
  collecting: 'Zbieranie dyspozycji',
  draft: 'Szkic grafiku',
  published: 'Grafik opublikowany',
}

/** "w grudniu" or "1–7 grudnia" with a capital letter for headings: "Grudzień" reads worse than "Okres: w grudniu". */
export function periodTitle(start: string, end: string): string {
  return periodWords(start, end)
}

/** "pt 27 listopada" */
export function shortDay(iso: string): string {
  const day = parseDate(iso)
  return `${weekdayShort(day)} ${dayAndMonth(day)}`
}

/** Days from today to the deadline: negative when it has passed. */
export function daysUntil(iso: string, today: Date = new Date()): number {
  return Math.round((parseDate(iso).getTime() - parseDate(toIsoDate(today)).getTime()) / 86_400_000)
}

/** "termin minął 2 dni temu", "termin: dziś", "termin za 5 dni" */
export function deadlineWords(iso: string, today: Date = new Date()): string {
  const days = daysUntil(iso, today)
  if (days === 0) return 'termin mija dziś'
  if (days === 1) return 'termin mija jutro'
  if (days > 1) return `do terminu ${days} dni`
  if (days === -1) return 'termin minął wczoraj'
  return `termin minął ${-days} dni temu`
}

/** "Anna Wróbel, Marek Zając i 4 inne osoby" */
export function namesList(names: string[], shown = 3): string {
  if (names.length <= shown) return names.join(', ')
  const rest = names.length - shown
  return `${names.slice(0, shown).join(', ')} i ${rest} ${rest === 1 ? 'inna osoba' : rest < 5 ? 'inne osoby' : 'innych osób'}`
}

/** 1 osoba, 2 osoby, 5 osób */
export function people(n: number): string {
  if (n === 1) return '1 osoba'
  const last = n % 10
  const teen = n % 100 >= 12 && n % 100 <= 14
  return `${n} ${last >= 2 && last <= 4 && !teen ? 'osoby' : 'osób'}`
}

/** "1 zmiana", "3 zmiany", "5 zmian" */
export function shifts(n: number): string {
  if (n === 1) return '1 zmiana'
  const last = n % 10
  const teen = n % 100 >= 12 && n % 100 <= 14
  return `${n} ${last >= 2 && last <= 4 && !teen ? 'zmiany' : 'zmian'}`
}

/** "1 zmiana bez obsady", "3 zmiany bez obsady" */
export const holesWords = (n: number) => `${shifts(n)} bez obsady`

/** "Okres próbny: zostało 9 dni" */
export function statusWords(data: Pick<SubscriptionOut, 'read_only' | 'trial' | 'days_left'>): string {
  if (data.read_only) return 'Tylko do oglądania'
  if (data.trial) return `Okres próbny: ${daysWords(data.days_left)}`
  return `Dostęp aktywny: ${daysWords(data.days_left)}`
}

function daysWords(days: number): string {
  return days === 1 ? 'został 1 dzień' : `zostało ${days} dni`
}
