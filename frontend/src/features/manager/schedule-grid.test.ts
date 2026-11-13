import { describe, expect, it } from 'vitest'

import type { VersionShiftOut } from '../../api/generated/model'
import { buildGrid, percent, swapChanges } from './schedule-grid'

function shift(id: string, date: string, start: string, end: string, type: string, position = 'p1'): VersionShiftOut {
  return {
    id,
    date,
    start_time: start,
    end_time: end,
    hours: 8,
    shift_type_name: type,
    position_id: position,
    position_name: position === 'p1' ? 'Sprzedawca' : 'Piekarz',
    employee_id: `e-${id}`,
    employee_name: `Osoba ${id}`,
    pinned: false,
    manual: false,
    borrowed: false,
    wish: 'neutral',
    problems: [],
    past: false,
  }
}

describe('buildGrid', () => {
  it('puts days in rows and shift types in columns ordered by start time', () => {
    const { columns, rows } = buildGrid(
      [
        shift('a', '2026-12-01', '14:00', '22:00', 'Popołudniowa'),
        shift('b', '2026-12-01', '06:00', '14:00', 'Ranna'),
        shift('c', '2026-12-01', '06:00', '14:00', 'Ranna'),
        shift('d', '2026-12-02', '22:00', '06:00', 'Nocna', 'p2'),
        shift('e', '2026-12-03', '07:00', '15:00', 'Ranna'),
      ],
      '2026-12-01',
      '2026-12-03',
    )

    expect(columns.map((c) => [c.shiftTypeName, c.start, c.end])).toEqual([
      ['Ranna', '06:00', '14:00'],
      ['Popołudniowa', '14:00', '22:00'],
      ['Nocna', '22:00', '06:00'],
    ])
    expect(rows.map((r) => r.date)).toEqual(['2026-12-01', '2026-12-02', '2026-12-03'])
    expect(rows[0].cells['Ranna|p1'].map((s) => s.id)).toEqual(['b', 'c'])
    expect(rows[1].cells['Ranna|p1']).toBeUndefined()
    expect(rows[2].cells['Ranna|p1'][0].start_time).toBe('07:00')
  })
})

describe('swapChanges', () => {
  it('swaps two people, or moves one to an empty shift', () => {
    const a = shift('a', '2026-12-01', '06:00', '14:00', 'Ranna')
    const hole = { ...shift('b', '2026-12-02', '06:00', '14:00', 'Ranna'), employee_id: null }
    expect(swapChanges(a, hole)).toEqual([
      { shift_id: 'b', employee_id: 'e-a' },
      { shift_id: 'a', employee_id: null },
    ])
  })
})

it('writes percentages the Polish way', () => {
  expect(percent(91.256)).toBe('91,3 %')
  expect(percent(100)).toBe('100 %')
})
