import { describe, expect, it } from 'vitest'

import { calendarWeeks } from './calendar-weeks'
import { cellHours, describeMark, NEUTRAL } from './marks'

describe('availability marks', () => {
  it('describes hours in plain words, including nights', () => {
    expect(describeMark({ state: 'prefer', from: '22:00', to: '06:00' })).toBe('chętnie, tylko 22:00–06:00 (do rana)')
    expect(describeMark({ state: 'cannot', from: '08:00', to: '12:00' })).toBe('nie mogę w godzinach 08:00–12:00')
    expect(cellHours({ state: 'prefer', from: '14:00', to: '22:30' })).toBe('14–22:30')
    expect(cellHours(NEUTRAL)).toBeNull()
  })

  it('lays the period out in Monday-first weeks', () => {
    const weeks = calendarWeeks('2026-12-01', '2026-12-31')
    expect(weeks).toHaveLength(5)
    expect(weeks[0][0]).toBeNull() // 1 December 2026 is a Tuesday
    expect(weeks[0][1]).toBe('2026-12-01')
    expect(weeks[4].filter(Boolean)).toEqual(['2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31'])
  })
})
