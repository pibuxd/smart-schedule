import { fireEvent, screen, waitFor, within } from '@testing-library/react'
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

const offer = {
  id: 'o1',
  shift: {
    date: '2026-11-20',
    start_time: '14:00',
    end_time: '22:00',
    hours: 8,
    location_id: 'l2',
    location_name: 'Bochnia',
    position_name: 'Sprzedawca',
    shift_type_name: 'Popołudniowa',
  },
  offered_by_name: 'Ola Kos',
  away: true,
  my_claim_id: null,
  my_claim_status: null,
}

function schedule(shifts: unknown[], offers: unknown[] = []) {
  return mockApi((method, path) => {
    if (path === '/api/me/offers') return [200, offers]
    if (method === 'POST' && path === '/api/me/shifts/a1/offer') return [201, { id: 'o9', status: 'open', notified: 3 }]
    if (method === 'POST' && path === '/api/offers/o1/claim') return [201, { ...offer, my_claim_id: 'c1', my_claim_status: 'pending' }]
    return [200, { home_location_name: 'Wieliczka – Rynek', shifts, months: [{ month: '2026-11', hours: 112 }] }]
  })
}

describe('MyScheduleScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the next shift as a big calendar page and the month total', async () => {
    schedule([shift])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    const next = await screen.findByRole('article', { name: 'Najbliższa zmiana' })
    expect(next).toHaveTextContent('jutro')
    expect(next).toHaveTextContent('13')
    expect(next).toHaveTextContent('6:00–14:00')
    expect(next).toHaveTextContent('Z Tobą: Anna Wróbel, Marek Zając')
    expect(screen.getByText('Razem w listopadzie')).toBeInTheDocument()
    expect(screen.getByText('112 godz.')).toBeInTheDocument()
  })

  it('gives a shift away after explaining that it stays mine until the manager decides', async () => {
    const calls = schedule([shift])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Oddaj tę zmianę' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText('Do decyzji kierownika to nadal Twoja zmiana.')).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Oddaj zmianę' }))
    expect(await within(sheet).findByText(/liczba osób: 3/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/me/shifts/a1/offer')).toBe(true)
  })

  it('shows a shift being given away and lets me keep it', async () => {
    schedule([{ ...shift, offer_id: 'o9', offer_status: 'claimed' }])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Oddajesz: czeka na kierownika' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Ktoś chce wziąć tę zmianę/)).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: 'Zostaję na tej zmianie' })).toBeInTheDocument()
  })

  it('lists shifts to take and says "Biorę"', async () => {
    const calls = schedule([shift], [offer])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    const section = await screen.findByRole('region', { name: 'Zmiany do wzięcia' })
    expect(section).toHaveTextContent('Bochnia (inny lokal). Oddaje: Ola Kos')
    fireEvent.click(within(section).getByRole('button', { name: 'Biorę' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/offers/o1/claim')).toBe(true))
  })

  it('hides giving away in read-only mode', async () => {
    schedule([shift])
    renderScreen(<MyScheduleScreen companyId="c1" readOnly today={new Date(2026, 10, 12)} />)
    await screen.findByRole('article', { name: 'Najbliższa zmiana' })
    expect(screen.queryByRole('button', { name: 'Oddaj tę zmianę' })).not.toBeInTheDocument()
  })

  it('explains an empty schedule and points to "Kiedy mogę"', async () => {
    schedule([])
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
