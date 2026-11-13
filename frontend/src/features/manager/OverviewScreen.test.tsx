import { fireEvent, screen, waitFor, within } from '@testing-library/react'
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
    latest_version_id: null,
    latest_version_status: null,
    active_run_id: null,
    manual_changes: 0,
  },
}

const overview = {
  company_id: 'c1',
  company_name: 'Złoty Kłos',
  role: 'owner',
  subscription: { read_only: false, read_only_message: '', never_started: false, trial: false, days_left: 20, expiring_soon: false },
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
    expect(await screen.findByText(/Powiadomienie w aplikacji wysłane \(osób: 2\)/)).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.url).toBe('/api/periods/p1/ask-availability')
    expect(post.body).toEqual({ only_missing: true })
  })

  it('arranges a schedule only when the manager confirms, warning who has not answered', async () => {
    const calls = mockApi((method) => (method === 'POST' ? [202, [{ id: 'r1', status: 'queued' }]] : [200, overview]))
    renderScreen(
      <AsManager>
        <OverviewScreen today={new Date(2026, 10, 12)} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ułóż grafik' }))
    expect(await screen.findByText(/Bez dyspozycji: 2 osoby/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Ułóż grafik' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/periods/generate')).toBe(true))
    expect(calls.find((c) => c.url === '/api/periods/generate')!.body).toEqual({ period_ids: ['p1'] })
  })

  it('warns before the deadline and about unpinned manual changes', async () => {
    const early = {
      ...overview,
      locations: [{ ...location, period: { ...location.period, deadline: '2026-11-20', latest_version_id: 'v1', latest_version_status: 'draft', manual_changes: 3 } }],
    }
    mockApi(() => [200, early])
    renderScreen(
      <AsManager>
        <OverviewScreen today={new Date(2026, 10, 12)} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ułóż od nowa' }))
    expect(await screen.findByText(/Termin dyspozycji jeszcze nie minął, a bez dyspozycji: 2 osoby/)).toBeInTheDocument()
    expect(screen.getByText(/usunie nieprzypięte ręczne poprawki: 3/)).toBeInTheDocument()
    expect(screen.getByText('Szkic czeka na publikację')).toBeInTheDocument()
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
