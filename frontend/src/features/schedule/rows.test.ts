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

  it('names a few coworkers and counts the rest with the right Polish form', () => {
    expect(coworkersText(['Anna', 'Marek'])).toBe('Anna, Marek')
    expect(coworkersText(['A', 'B', 'C', 'D', 'E'])).toBe('A, B, C i 2 inne osoby')
    expect(coworkersText(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])).toBe('A, B, C i 5 innych osób')
  })
})
