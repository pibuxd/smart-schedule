import { describe, expect, it } from 'vitest'

import type { LocationOut, PeriodOut } from '../../api/generated/model'
import { nextPeriodDates, pickPeriod } from './periods'

const location = { schedule_period: 'month', availability_deadline_days: 7 } as LocationOut
const period = (start: string, end: string) => ({ id: start, start, end }) as PeriodOut

describe('periods', () => {
  it('suggests the month after the last period, with the default deadline', () => {
    expect(nextPeriodDates(location, [period('2026-12-01', '2026-12-31')], new Date(2026, 10, 12))).toEqual({
      start: '2027-01-01',
      end: '2027-01-31',
      deadline: '2026-12-25',
    })
    expect(nextPeriodDates(location, [], new Date(2026, 10, 12)).start).toBe('2026-12-01')
  })

  it('suggests next Monday for a weekly location', () => {
    const weekly = { ...location, schedule_period: 'week', availability_deadline_days: 3 } as LocationOut
    expect(nextPeriodDates(weekly, [], new Date(2026, 10, 12))).toEqual({
      start: '2026-11-16',
      end: '2026-11-22',
      deadline: '2026-11-13',
    })
  })

  it('picks the current or next period first', () => {
    const list = [period('2026-10-01', '2026-10-31'), period('2026-12-01', '2026-12-31'), period('2026-11-01', '2026-11-30')]
    expect(pickPeriod(list, new Date(2026, 10, 12))?.start).toBe('2026-11-01')
    expect(pickPeriod(list, new Date(2027, 1, 1))?.start).toBe('2026-12-01')
  })
})
