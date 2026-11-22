// Amounts of money in złoty: the estimated pay next to the hours and the hourly rates of positions.

const PLN = new Intl.NumberFormat('pl-PL', { style: 'currency', currency: 'PLN' })

/** 3768 -> "3768,00 zł", 12345.5 -> "12 345,50 zł" (Polish grouping and a decimal comma). */
export function moneyText(value: number): string {
  return PLN.format(value)
}

/** An hourly rate: 31.4 -> "31,40 zł/h". */
export function rateText(value: number): string {
  return `${moneyText(value)}/h`
}

/** What the manager typed as a rate -> złoty: "31,40", "31.4" or " 36 zł " -> 31.4 / 36; "" -> null; else NaN. */
export function parseRate(value: string): number | null {
  const text = value.replace(/zł/i, '').replace(/\s/g, '').replace(',', '.')
  if (text === '') return null
  return /^\d+(\.\d{1,2})?$/.test(text) ? Number(text) : Number.NaN
}

/** A rate shown in an input: 31.4 -> "31,40"; null -> "". */
export function rateInput(value: number | null | undefined): string {
  return value == null ? '' : value.toFixed(2).replace('.', ',')
}

export const BAD_RATE = 'Wpisz stawkę w złotych, np. 31,40.'
