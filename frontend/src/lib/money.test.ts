import { describe, expect, it } from 'vitest'

import { fullDay, moneyText, parseRate, rateInput, rateText, stepOn, stepsAfter } from './money'

const plain = (text: string) => text.replace(/\s/g, ' ')

describe('money', () => {
  it('writes złoty the Polish way', () => {
    expect(plain(moneyText(3768))).toBe('3768,00 zł')
    expect(plain(moneyText(12345.5))).toBe('12 345,50 zł')
    expect(plain(rateText(31.4))).toBe('31,40 zł/h')
  })

  it('reads a rate typed with a comma, a dot or the currency', () => {
    expect(parseRate('31,40')).toBe(31.4)
    expect(parseRate(' 36 zł ')).toBe(36)
    expect(parseRate('31.4')).toBe(31.4)
    expect(parseRate('')).toBeNull()
    expect(parseRate('trzydzieści')).toBeNaN()
    expect(parseRate('31,405')).toBeNaN()
    expect(parseRate('-5')).toBeNaN()
  })

  it('shows a rate in an input with grosze', () => {
    expect(rateInput(31.4)).toBe('31,40')
    expect(rateInput(null)).toBe('')
  })

  it('finds the rate of a day among its steps', () => {
    const steps = [
      { id: 'b', valid_from: '2026-12-01', hourly_rate: 34 },
      { id: 'a', valid_from: null, hourly_rate: 30 },
      { id: 'c', valid_from: '2027-01-01', hourly_rate: null },
    ]
    expect(stepOn(steps, '2026-11-30')?.id).toBe('a')
    expect(stepOn(steps, '2026-12-01')?.id).toBe('b')
    expect(stepOn(steps, '2027-02-01')?.hourly_rate).toBeNull()
    expect(stepOn(steps.slice(0, 1), '2026-11-30')).toBeUndefined()
    expect(stepsAfter(steps, '2026-11-30').map((s) => s.id)).toEqual(['b', 'c'])
    expect(fullDay('2026-12-01')).toBe('1 grudnia 2026')
  })
})
