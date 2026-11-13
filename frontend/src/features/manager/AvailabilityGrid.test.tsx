import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AvailabilityGrid } from './AvailabilityGrid'

const data = {
  period: {
    id: 'p1',
    location_id: 'l1',
    location_name: 'Wieliczka',
    start: '2026-12-01',
    end: '2026-12-03',
    status: 'collecting' as const,
    deadline: '2026-11-24',
    requested_at: null,
  },
  employees: [
    {
      id: 'e1',
      name: 'Anna Wróbel',
      positions: ['Sprzedawca'],
      submitted_at: null,
      late_days: 1,
      days: [
        { date: '2026-12-01', state: 'cannot' as const, from_time: null, to_time: null, late: false },
        { date: '2026-12-02', state: 'prefer' as const, from_time: '06:00:00', to_time: '14:00:00', late: true },
      ],
    },
  ],
}

describe('AvailabilityGrid', () => {
  it('describes every day in words, with hours and the late mark', () => {
    render(<AvailabilityGrid data={data} />)
    expect(screen.getByRole('img', { name: 'wtorek 1 grudnia: nie mogę' })).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'środa 2 grudnia: chętnie 6–14, zmienione po terminie' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'czwartek 3 grudnia: mogę' })).toBeInTheDocument()
    expect(screen.getByText('Nie wysłano')).toBeInTheDocument()
  })
})
