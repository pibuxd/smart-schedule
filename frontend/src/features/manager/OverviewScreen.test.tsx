import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { OverviewScreen } from './OverviewScreen'
import { AsManager } from './test-utils'

const location = {
  id: 'l1',
  name: 'Wieliczka – Rynek',
  address: 'Rynek Górny 4',
  group_id: 'g1',
  group_name: 'Piekarnie pod Krakowem',
  schedule_period: 'month',
  availability_deadline_days: 7,
  archived: false,
  employees: 3,
  pending_invitations: 0,
  period: {
    id: 'p1',
    start: '2026-12-01',
    end: '2026-12-31',
    status: 'collecting',
    deadline: '2026-11-10',
    availability_requested_at: '2026-11-03T09:00:00+01:00',
    submitted: 1,
    missing: ['Anna Wróbel', 'Marek Zając'],
    late_days: 2,
  },
}

const overview = {
  company_id: 'c1',
  company_name: 'Złoty Kłos',
  role: 'owner',
  subscription: { read_only: false, read_only_message: '', never_started: false, days_left: 20, expiring_soon: false },
  groups: [{ id: 'g1', name: 'Piekarnie pod Krakowem' }],
  locations: [location],
  archived: [],
}

describe('OverviewScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows who is missing, late changes, and that the schedule can be arranged after the deadline', async () => {
    mockApi(() => [200, overview])
    renderScreen(
      <AsManager>
        <OverviewScreen today={new Date(2026, 10, 12)} />
      </AsManager>,
    )
    expect(await screen.findByText('Wieliczka – Rynek')).toBeInTheDocument()
    expect(screen.getByText('Wysłali dyspozycje: 1 z 3')).toBeInTheDocument()
    expect(screen.getByText('Anna Wróbel, Marek Zając')).toBeInTheDocument()
    expect(screen.getByText('Zmiany po terminie: 2 dni')).toBeInTheDocument()
    expect(screen.getByText(/Termin minął. Można układać grafik/)).toBeInTheDocument()
  })

  it('reminds only those who have not answered', async () => {
    const calls = mockApi((method) =>
      method === 'POST' ? [200, { period: {}, notified: 2 }] : [200, overview],
    )
    renderScreen(
      <AsManager>
        <OverviewScreen today={new Date(2026, 10, 12)} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Przypomnij (2)' }))
    expect(await screen.findByText(/Zapisane w aplikacji dla: 2 osoby\./)).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.url).toBe('/api/periods/p1/ask-availability')
    expect(post.body).toEqual({ only_missing: true })
  })

  it('has an empty state and an error state', async () => {
    mockApi(() => [200, { ...overview, locations: [] }])
    const { unmount } = renderScreen(
      <AsManager>
        <OverviewScreen />
      </AsManager>,
    )
    expect(await screen.findByText('Nie masz jeszcze żadnego lokalu')).toBeInTheDocument()
    unmount()
    mockApi(() => [500, {}])
    renderScreen(
      <AsManager>
        <OverviewScreen />
      </AsManager>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać lokali')
  })
})
