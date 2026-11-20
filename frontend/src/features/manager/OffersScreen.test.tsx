import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { OffersScreen } from './OffersScreen'
import { AsManager } from './test-utils'

const offer = {
  id: 'o1',
  assignment_id: 'a1',
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

const overview = { groups: [], locations: [{ id: 'l1', name: 'Rynek' }] }
const row = (id: string, employee: string, date = '2026-12-04') => ({
  id,
  version_id: 'v1',
  shift: { ...offer.shift, date },
  employee_id: `e-${id}`,
  employee_name: employee,
  started: false,
  offer_id: null,
})
const candidates = [
  { employee_id: 'e1', name: 'Ala Nowak', home_location_name: 'Bochnia', here: false, wants: true, problems: [] },
  {
    employee_id: 'e2',
    name: 'Jan Wrona',
    home_location_name: 'Rynek',
    here: true,
    wants: false,
    problems: ['Jan Wrona ma zaznaczone „nie mogę”.'],
  },
]

/** Answers for the screen with one offer and two published shifts on different days. */
function api(method: string, path: string): [number, unknown] {
  if (path === '/api/manager/offers') return [200, { offers: [offer], waiting: 2 }]
  if (path === '/api/manager/overview') return [200, overview]
  if (path === '/api/locations/l1/handover-shifts') {
    return [200, [row('a1', 'Ola Kos'), row('a2', 'Ewa Lis', '2026-12-05')]]
  }
  if (path.endsWith('/handover-candidates')) return [200, candidates]
  if (path === '/api/shift-swaps/check') return [200, { problems: [] }]
  if (method === 'POST') return [200, { id: 'o1', status: 'rejected', notified: 0 }]
  return [404, {}]
}

describe('OffersScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lets the manager pick any person for an offered shift, also against the rules', async () => {
    const calls = mockApi(api)
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Wybierz osobę sam' }))
    const sheet = await screen.findByRole('dialog')
    expect(await within(sheet).findByText('chce wziąć')).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Wpisz mimo to: Jan Wrona' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/assignments/a1/reassign')?.body).toEqual({
        employee_id: 'e2',
        force: true,
      }),
    )
  })

  it('folds people from other locations under "Z innych lokali" and puts one of them on the shift', async () => {
    const calls = mockApi(api)
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Wybierz osobę sam' }))
    const sheet = await screen.findByRole('dialog')
    const summary = await within(sheet).findByText('Z innych lokali (1)')
    const folded = summary.closest('details')!
    expect(folded).not.toHaveAttribute('open')
    expect(within(summary).getByText('chce wziąć: 1')).toBeInTheDocument()
    expect(within(summary).getByText('mogą przyjść: 1')).toBeInTheDocument()
    expect(folded).not.toContainElement(within(sheet).getByRole('button', { name: 'Wpisz mimo to: Jan Wrona' }))
    // Open it as the manager does, then pick the person from the other location.
    fireEvent.click(summary)
    expect(folded).toHaveAttribute('open')
    expect(within(folded).getByText('Bochnia')).toBeInTheDocument()
    fireEvent.click(within(folded).getByRole('button', { name: 'Wpisz: Ala Nowak' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/assignments/a1/reassign')?.body).toEqual({
        employee_id: 'e1',
        force: false,
      }),
    )
  })

  it('opens "Z innych lokali" at once when nobody from the location can be put there', async () => {
    mockApi((method, path) =>
      path.endsWith('/handover-candidates') ? [200, [candidates[0]]] : api(method, path),
    )
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Wybierz osobę sam' }))
    const sheet = await screen.findByRole('dialog')
    expect(await within(sheet).findByText('Z tego lokalu nie ma kogo tu wpisać.')).toBeInTheDocument()
    expect(within(sheet).getByText('Z innych lokali (1)').closest('details')).toHaveAttribute('open')
  })

  it('ends an offer for the employee', async () => {
    const calls = mockApi(api)
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Zakończ oddawanie' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/offers/o1/close')).toBe(true))
  })

  it('swaps two people from the list of published shifts', async () => {
    const calls = mockApi(api)
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Zmień: Ola Kos/ }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Zamień z inną zmianą' }))
    fireEvent.click(await within(sheet).findByRole('button', { name: /Ewa Lis/ }))
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Zamień' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/shift-swaps')?.body).toEqual({
        first_id: 'a1',
        second_id: 'a2',
        force: false,
      }),
    )
  })

  it('shows volunteers and approves one who can take the shift', async () => {
    const calls = mockApi((method, path) =>
      method === 'POST' && path === '/api/claims/c1/approve'
        ? [200, { id: 'o1', status: 'approved', notified: 0 }]
        : api(method, path),
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
    mockApi((method, path) => (path === '/api/manager/offers' ? [200, { offers: [], waiting: 0 }] : api(method, path)))
    show()
    expect(await screen.findByText('Nikt nie oddaje teraz zmian')).toBeInTheDocument()
  })

  it('shows a plain error with a retry button', async () => {
    mockApi((method, path) => (path === '/api/manager/offers' ? [500, {}] : api(method, path)))
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać oddanych zmian')
  })

  it('does not decide in read-only mode', async () => {
    mockApi(api)
    show(true)
    expect(await screen.findByRole('button', { name: 'Zatwierdź: Ala Nowak' })).toBeDisabled()
  })
})
