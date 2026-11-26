import { describe, expect, it } from 'vitest'

import { calendarWeeks } from './calendar-weeks'
import { cellHours, describeMark, NEUTRAL } from './marks'

describe('availability marks', () => {
  it('describes hours in plain words, including nights', () => {
    expect(describeMark({ state: 'prefer', from: '22:00', to: '06:00' })).toBe('chętnie, tylko 22:00–06:00 (do rana)')
    expect(describeMark({ state: 'cannot', from: null, to: null })).toBe('nie mogę')
    // "Nie mogę od 9 do 11" is marked as "mogę do 9:00 lub od 11:00" ("nie mogę" is always the whole day).
    const rest = { state: 'neutral' as const, from: '00:00', to: '09:00', from2: '11:00', to2: '00:00' }
    expect(describeMark(rest)).toBe('mogę, tylko do 09:00 lub od 11:00')
    expect(cellHours(rest)).toBe('do 9/od 11')
    expect(describeMark({ state: 'prefer', from: '14:00', to: '00:00' })).toBe('chętnie, tylko od 14:00')
    expect(cellHours({ state: 'prefer', from: '14:00', to: '22:30' })).toBe('14–22:30')
    expect(cellHours(NEUTRAL)).toBeNull()
    const two = { state: 'neutral' as const, from: '06:00', to: '10:00', from2: '16:00', to2: '22:00' }
    expect(describeMark(two)).toBe('mogę, tylko 06:00–10:00 lub 16:00–22:00')
    expect(describeMark({ ...two, oneShift: true })).toBe('mogę, tylko 06:00–10:00 albo 16:00–22:00 (jedna zmiana)')
    expect(cellHours(two)).toBe('6–10/16–22')
  })

  it('lays the period out in Monday-first weeks', () => {
    const weeks = calendarWeeks('2026-12-01', '2026-12-31')
    expect(weeks).toHaveLength(5)
    expect(weeks[0][0]).toBeNull() // 1 December 2026 is a Tuesday
    expect(weeks[0][1]).toBe('2026-12-01')
    expect(weeks[4].filter(Boolean)).toEqual(['2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31'])
  })
})
