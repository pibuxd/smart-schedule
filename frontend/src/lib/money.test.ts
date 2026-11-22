import { describe, expect, it } from 'vitest'

import { moneyText, parseRate, rateInput, rateText } from './money'

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
})
