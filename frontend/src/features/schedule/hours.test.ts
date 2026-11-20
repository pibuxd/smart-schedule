import { describe, expect, it } from 'vitest'

import { clockTime, differenceSentence, differenceText, isTime, lengthText, minutesBetween } from './hours'

describe('hours', () => {
  it('reads times of day', () => {
    expect(isTime('06:00')).toBe(true)
    expect(isTime('6:30')).toBe(true)
    expect(isTime('23:59')).toBe(true)
    expect(isTime('')).toBe(false)
    expect(isTime('24:00')).toBe(false)
    expect(isTime('6')).toBe(false)
  })

  it('counts a night shift into the next day', () => {
    expect(minutesBetween('06:00', '14:30')).toBe(510)
    expect(minutesBetween('22:00', '06:00')).toBe(480)
    expect(minutesBetween('06:00', '06:00')).toBe(24 * 60)
  })

  it('says how much longer or shorter in plain words', () => {
    expect(lengthText(90)).toBe('1 h 30 min')
    expect(lengthText(-120)).toBe('2 h')
    expect(lengthText(45)).toBe('45 min')
    expect(differenceText(60)).toBe('nadgodziny: +1 h')
    expect(differenceText(-150)).toBe('krócej o 2 h 30 min')
    expect(differenceText(0)).toBe('tyle, ile w grafiku')
    expect(differenceSentence(-120)).toBe('Krócej o 2 h')
  })

  it('writes the clock time with two digits', () => {
    expect(clockTime(new Date(2026, 10, 20, 9, 5))).toBe('09:05')
  })
})
