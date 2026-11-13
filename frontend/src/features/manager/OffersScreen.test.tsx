import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { OffersScreen } from './OffersScreen'
import { AsManager } from './test-utils'

const offer = {
  id: 'o1',
  status: 'claimed',
  shift: {
    date: '2026-12-04',
    start_time: '06:00',
    end_time: '14:00',
    hours: 8,
    location_id: 'l1',
    location_name: 'Rynek',
    position_name: 'Sprzedawca',
    shift_type_name: 'Ranna',
  },
  offered_by_name: 'Ola Kos',
  created_at: '2026-12-01T10:00:00+01:00',
  decided_at: null,
  claims: [
    {
      id: 'c1',
      employee_id: 'e1',
      name: 'Ala Nowak',
      home_location_name: 'Bochnia',
      status: 'pending',
      created_at: '2026-12-01T11:00:00+01:00',
      problems: [],
    },
    {
      id: 'c2',
      employee_id: 'e2',
      name: 'Jan Wrona',
      home_location_name: 'Rynek',
      status: 'pending',
      created_at: '2026-12-01T12:00:00+01:00',
      problems: ['Jan Wrona ma zaznaczone „nie mogę” (04.12 Ranna 06:00–14:00).'],
    },
  ],
}

function show(readOnly = false) {
  renderScreen(
    <AsManager readOnly={readOnly}>
      <OffersScreen />
    </AsManager>,
  )
}

describe('OffersScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows volunteers and approves one who can take the shift', async () => {
    const calls = mockApi((method, path) =>
      method === 'POST' && path === '/api/claims/c1/approve'
        ? [200, { id: 'o1', status: 'approved', notified: 0 }]
        : [200, { offers: [offer], waiting: 2 }],
    )
    show()
    const card = (await screen.findByText('Oddaje: Ola Kos')).closest('li')!
    expect(within(card).getByText('Czeka na Twoją decyzję')).toBeInTheDocument()
    expect(within(card).getByText('Na co dzień: Bochnia')).toBeInTheDocument()
    expect(within(card).getByText(/Jan Wrona ma zaznaczone „nie mogę”/)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Zatwierdź: Jan Wrona' })).toBeDisabled()
    fireEvent.click(within(card).getByRole('button', { name: 'Zatwierdź: Ala Nowak' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/claims/c1/approve')).toBe(true))
  })

  it('explains an empty list', async () => {
    mockApi(() => [200, { offers: [], waiting: 0 }])
    show()
    expect(await screen.findByText('Nikt nie oddaje teraz zmian')).toBeInTheDocument()
  })

  it('shows a plain error with a retry button', async () => {
    mockApi(() => [500, {}])
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać oddanych zmian')
  })

  it('does not decide in read-only mode', async () => {
    mockApi(() => [200, { offers: [offer], waiting: 2 }])
    show(true)
    expect(await screen.findByRole('button', { name: 'Zatwierdź: Ala Nowak' })).toBeDisabled()
  })
})
