// Amounts of money in złoty: the pay next to the hours, hourly rates by day, and supplements (docs/plan.md, 35).

import { dayAndMonth, parseDate } from './dates'

const PLN = new Intl.NumberFormat('pl-PL', { style: 'currency', currency: 'PLN' })

/** 3768 -> "3768,00 zł", 12345.5 -> "12 345,50 zł" (Polish grouping and a decimal comma). */
export function moneyText(value: number): string {
  return PLN.format(value)
}

/** An hourly rate: 31.4 -> "31,40 zł/h". */
export function rateText(value: number): string {
  return `${moneyText(value)}/h`
}

/** What the manager typed as an amount -> złoty: "31,40", "31.4" or " 36 zł " -> 31.4 / 36; "" -> null; else NaN. */
export function parseRate(value: string): number | null {
  const text = value.replace(/zł/i, '').replace(/%/, '').replace(/\s/g, '').replace(',', '.')
  if (text === '') return null
  return /^\d+(\.\d{1,2})?$/.test(text) ? Number(text) : Number.NaN
}

/** An amount shown in an input: 31.4 -> "31,40"; null -> "". */
export function rateInput(value: number | null | undefined): string {
  return value == null ? '' : value.toFixed(2).replace('.', ',')
}

export const BAD_RATE = 'Wpisz stawkę w złotych, np. 31,40.'

/** "2026-11-10" -> "10 listopada 2026" */
export function fullDay(iso: string): string {
  const date = parseDate(iso)
  return `${dayAndMonth(date)} ${date.getFullYear()}`
}

/** One step of a rate: from `valid_from` (null = from the start) until the next step. */
export type RateStep = { id: string; valid_from: string | null; hourly_rate: number | null }

/** The step that counts on `day` ("YYYY-MM-DD"), or undefined before the first one. */
export function stepOn<T extends RateStep>(steps: T[], day: string): T | undefined {
  return [...steps]
    .sort(byDay)
    .filter((s) => s.valid_from === null || s.valid_from <= day)
    .at(-1)
}

/** Steps that start after `day`, earliest first (a raise entered ahead). */
export function stepsAfter<T extends RateStep>(steps: T[], day: string): T[] {
  return [...steps].sort(byDay).filter((s) => s.valid_from !== null && s.valid_from > day)
}

export function byDay(a: RateStep, b: RateStep): number {
  if (a.valid_from === b.valid_from) return 0
  if (a.valid_from === null) return -1
  if (b.valid_from === null) return 1
  return a.valid_from < b.valid_from ? -1 : 1
}
