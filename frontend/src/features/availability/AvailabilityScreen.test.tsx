import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MyAvailabilityOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { AvailabilityScreen } from './AvailabilityScreen'

const period = {
  id: 'p1',
  location_name: 'Wieliczka – Rynek',
  start: '2026-12-01',
  end: '2026-12-31',
  status: 'collecting' as const,
  deadline: '2099-11-24',
  editable: true,
}

function availability(over: Partial<MyAvailabilityOut> = {}): MyAvailabilityOut {
  return {
    period,
    days: [{ date: '2026-12-04', state: 'prefer', from_time: '22:00:00', to_time: '06:00:00' }],
    submitted_at: null,
    ...over,
  }
}

function api(data: MyAvailabilityOut) {
  return mockApi((method, path) => {
    if (path === '/api/me/requests') return [200, []]
    if (method === 'GET') return [200, data]
    return [200, data]
  })
}

describe('AvailabilityScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says plainly when there is nothing to mark yet', async () => {
    api({ period: null, days: [], submitted_at: null })
    renderScreen(<AvailabilityScreen companyId="c1" readOnly={false} />)
    expect(await screen.findByText('Na razie nie ma czego zaznaczać')).toBeInTheDocument()
  })

  it('shows states with words for screen readers, including night hours', async () => {
    api(availability())
    renderScreen(<AvailabilityScreen companyId="c1" readOnly={false} />)
    const day = await screen.findByRole('button', { name: 'piątek 4 grudnia: chętnie, tylko 22:00–06:00 (do rana)' })
    expect(day).toHaveTextContent('22–6')
    expect(screen.getByRole('button', { name: 'wtorek 1 grudnia: obojętnie' })).toBeInTheDocument()
  })

  it('marks a day with the chosen state, saves it, and undoes it', async () => {
    const calls = api(availability())
    renderScreen(<AvailabilityScreen companyId="c1" readOnly={false} />)
    await screen.findByText('Zaznaczam dni jako:')
    fireEvent.click(screen.getByRole('button', { name: 'Nie mogę' }))
    // A keyboard press (detail 0) paints one day, like a tap does.
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: obojętnie' }), { detail: 0 })
    expect(screen.getByRole('button', { name: 'wtorek 1 grudnia: nie mogę' })).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(1))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      company_id: 'c1',
      period_id: 'p1',
      days: [{ date: '2026-12-01', state: 'cannot', from_time: null, to_time: null }],
    })

    fireEvent.click(screen.getByRole('button', { name: 'Cofnij' }))
    expect(screen.getByRole('button', { name: 'wtorek 1 grudnia: obojętnie' })).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(2))
    expect(calls.filter((c) => c.method === 'PUT')[1].body).toMatchObject({
      days: [{ date: '2026-12-01', state: 'neutral' }],
    })
  })

  it('warns plainly that "chętnie" with hours blocks other shifts that day', async () => {
    api(availability())
    renderScreen(<AvailabilityScreen companyId="c1" readOnly={false} />)
    fireEvent.click(await screen.findByRole('button', { name: /Godziny dnia/ }))
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: obojętnie' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Chętnie' }))
    fireEvent.click(screen.getByRole('radio', { name: /Mogę tylko w tych godzinach/ }))
    expect(screen.getByText('Zmiany spoza godzin 14:00–22:00 tego dnia nie dostaniesz.')).toBeInTheDocument()
  })

  it('opens a day with its hours when it is tapped with the state it already has', async () => {
    api(availability())
    renderScreen(<AvailabilityScreen companyId="c1" readOnly={false} />)
    expect(await screen.findByText('Dni z godzinami')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Chętnie' }))
    fireEvent.click(screen.getByRole('button', { name: /^piątek 4 grudnia: chętnie/ }), { detail: 0 })
    expect(await screen.findByRole('dialog', { name: 'piątek 4 grudnia' })).toBeInTheDocument()
    expect(screen.getByLabelText('Od')).toHaveValue('22:00')
    expect(screen.getByLabelText('Do')).toHaveValue('06:00')
  })

  it('cannot be changed when the company is read-only', async () => {
    api(availability())
    renderScreen(<AvailabilityScreen companyId="c1" readOnly />)
    expect(await screen.findByText(/wstrzymany dostęp/)).toBeInTheDocument()
    expect(screen.queryByText('Zaznaczam dni jako:')).not.toBeInTheDocument()
  })
})
