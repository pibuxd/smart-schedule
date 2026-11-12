import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { MyScheduleScreen } from './MyScheduleScreen'

const shift = {
  id: 'a1',
  date: '2026-11-13',
  start_at: '2026-11-13T06:00:00+01:00',
  end_at: '2026-11-13T14:00:00+01:00',
  start_time: '06:00',
  end_time: '14:00',
  hours: 8,
  location_name: 'Wieliczka – Rynek',
  position_name: 'Sprzedawca',
  shift_type_name: 'Ranna',
  away: false,
  coworkers: ['Anna Wróbel', 'Marek Zając'],
}

describe('MyScheduleScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the next shift as a big calendar page and the month total', async () => {
    mockApi(() => [200, { home_location_name: 'Wieliczka – Rynek', shifts: [shift], months: [{ month: '2026-11', hours: 112 }] }])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    const next = await screen.findByRole('article', { name: 'Najbliższa zmiana' })
    expect(next).toHaveTextContent('jutro')
    expect(next).toHaveTextContent('13')
    expect(next).toHaveTextContent('6:00–14:00')
    expect(next).toHaveTextContent('Z Tobą: Anna Wróbel, Marek Zając')
    expect(screen.getByText('Razem w listopadzie')).toBeInTheDocument()
    expect(screen.getByText('112 godz.')).toBeInTheDocument()
  })

  it('explains an empty schedule and points to "Kiedy mogę"', async () => {
    mockApi(() => [200, { home_location_name: 'Wieliczka – Rynek', shifts: [], months: [{ month: '2026-11', hours: 0 }] }])
    renderScreen(<MyScheduleScreen companyId="c1" />)
    expect(await screen.findByText('Nie masz jeszcze zmian w grafiku')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'kiedy możesz pracować' })).toBeInTheDocument()
  })

  it('shows a plain error with a retry button', async () => {
    mockApi(() => [500, {}])
    renderScreen(<MyScheduleScreen companyId="c1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać grafiku')
    expect(screen.getByRole('button', { name: 'Spróbuj jeszcze raz' })).toBeInTheDocument()
  })
})
