import { describe, expect, it } from 'vitest'

import type { MyShiftOut } from '../../api/generated/model'
import { buildRows, coworkersText } from './rows'

function shift(date: string, id = date): MyShiftOut {
  return {
    id,
    date,
    start_at: `${date}T06:00:00+01:00`,
    end_at: `${date}T14:00:00+01:00`,
    start_time: '06:00',
    end_time: '14:00',
    hours: 8,
    location_name: 'Wieliczka – Rynek',
    position_name: 'Sprzedawca',
    shift_type_name: 'Ranna',
    away: false,
    coworkers: [],
  }
}

describe('Mój grafik list', () => {
  it('shows days off between shifts and a line at each new week', () => {
    const rows = buildRows(shift('2026-11-13'), [shift('2026-11-14'), shift('2026-11-16')])
    expect(rows.map((r) => r.kind)).toEqual(['shift', 'off', 'week', 'shift'])
    expect(rows[2]).toMatchObject({ label: 'Tydzień 16–22 listopada' })
  })

  it('goes on to the end of the published schedule, so a free last day is shown', () => {
    const rows = buildRows(shift('2026-12-29'), [shift('2026-12-30')], '2026-12-31')
    expect(rows.map((r) => r.kind)).toEqual(['shift', 'off'])
    expect(buildRows(shift('2026-12-30'), [], '2026-12-31').map((r) => r.kind)).toEqual(['off'])
  })

  it('calls a day off only a day of a published schedule', () => {
    // Tests of PR #82 (26.11.2026): with November and February published, December and January looked free.
    const published = [
      { start: '2026-11-26', end: '2026-11-30' },
      { start: '2027-02-01', end: '2027-02-28' },
    ]
    const rows = buildRows(shift('2026-11-30'), [shift('2027-02-01')], '2027-02-02', published)
    expect(rows.map((r) => r.kind)).toEqual(['unpublished', 'week', 'shift', 'off'])
    expect(rows[0]).toMatchObject({ from: new Date(2026, 11, 1), to: new Date(2027, 0, 31) })
    expect(rows[1]).toMatchObject({ label: 'Tydzień 1–7 lutego' })
  })

  it('names a few coworkers and counts the rest with the right Polish form', () => {
    expect(coworkersText(['Anna', 'Marek'])).toBe('Anna, Marek')
    expect(coworkersText(['A', 'B', 'C', 'D', 'E'])).toBe('A, B, C i 2 inne osoby')
    expect(coworkersText(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])).toBe('A, B, C i 5 innych osób')
  })
})
