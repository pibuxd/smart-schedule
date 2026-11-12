import { describe, expect, it } from 'vitest'

import { calendarWeeks } from './calendar-weeks'
import { cellHours, changedDays, describeMark, type Marks, marksToReplace, NEUTRAL, replaceNote } from './marks'

describe('availability marks', () => {
  it('remembers only the days that changed, with their previous state (for "Cofnij")', () => {
    const before: Marks = { '2026-12-01': { state: 'cannot', from: null, to: null } }
    const after: Marks = {
      '2026-12-01': { state: 'cannot', from: null, to: null },
      '2026-12-02': { state: 'prefer', from: null, to: null },
    }
    expect(changedDays(before, after)).toEqual({ '2026-12-02': NEUTRAL })
  })

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

describe('overwrite note', () => {
  const marks: Marks = {
    '2026-12-01': { state: 'cannot', from: null, to: null },
    '2026-12-02': { state: 'prefer', from: null, to: null },
    '2026-12-03': { state: 'neutral', from: '14:00', to: '22:00' },
  }
  const dates = ['2026-12-01', '2026-12-02', '2026-12-03', '2026-12-04']

  it('counts marked days that would change', () => {
    expect(marksToReplace(marks, dates)).toBe(3)
    expect(marksToReplace(marks, dates, { state: 'cannot', from: null, to: null })).toBe(2)
  })

  it('uses Polish plurals', () => {
    expect(replaceNote(0)).toBeNull()
    expect(replaceNote(1)).toBe('Zastąpi 1 zaznaczony dzień w tym miesiącu.')
    expect(replaceNote(3)).toBe('Zastąpi 3 zaznaczone dni w tym miesiącu.')
    expect(replaceNote(12)).toBe('Zastąpi 12 zaznaczonych dni w tym miesiącu.')
    expect(replaceNote(22)).toBe('Zastąpi 22 zaznaczone dni w tym miesiącu.')
  })
})
