import { describe, expect, it } from 'vitest'

import { hoursText, parseDate, periodWords, relativeDay, shortTime, weekdayGenitive } from './dates'

describe('Polish date words', () => {
  it('names a whole month and a week', () => {
    expect(periodWords('2026-12-01', '2026-12-31')).toBe('w grudniu')
    expect(periodWords('2026-12-07', '2026-12-13')).toBe('7–13 grudnia')
    expect(periodWords('2026-11-30', '2026-12-06')).toBe('30 listopada – 6 grudnia')
  })

  it('says when the next shift is', () => {
    const today = parseDate('2026-11-12')
    expect(relativeDay(parseDate('2026-11-12'), today)).toBe('dzisiaj')
    expect(relativeDay(parseDate('2026-11-13'), today)).toBe('jutro')
    expect(relativeDay(parseDate('2026-11-14'), today)).toBe('pojutrze')
    expect(relativeDay(parseDate('2026-11-20'), today)).toBe('za 8 dni')
  })

  it('writes hours and times the Polish way', () => {
    expect(hoursText(112)).toBe('112 godz.')
    expect(hoursText(7.5)).toBe('7,5 godz.')
    expect(shortTime('06:00:00')).toBe('6:00')
    expect(weekdayGenitive(parseDate('2026-11-24'))).toBe('wtorku')
  })
})
