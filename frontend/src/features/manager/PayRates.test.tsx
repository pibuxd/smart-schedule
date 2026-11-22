import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { OwnRates, PaySection } from './PayRates'
import { AsManager } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const today = new Date(2026, 10, 22)
const night = {
  id: 'n1',
  name: 'Noc',
  start_time: '22:00:00',
  end_time: '06:00:00',
  weekdays: [0, 1, 2, 3, 4, 5, 6],
  kind: 'amount',
  value: 6,
  all_positions: true,
  position_ids: [],
  valid_from: null,
  valid_until: null,
}
const settings = {
  positions: [
    {
      position_id: 'p1',
      name: 'Sprzedawca',
      rates: [
        { id: 'r1', valid_from: null, hourly_rate: 31.4 },
        { id: 'r2', valid_from: '2027-01-01', hourly_rate: 33 },
      ],
    },
    { position_id: 'p2', name: 'Piekarz', rates: [] },
  ],
  supplements: [
    night,
    { ...night, id: 'n0', name: 'Niedziela', start_time: '00:00:00', end_time: '00:00:00', weekdays: [6], kind: 'percent', value: 50, all_positions: false, position_ids: ['p2'], valid_until: '2026-10-31' },
  ],
}

function show() {
  const calls = mockApi((method, path) => {
    if (path === '/api/locations/l1/pay-settings') return [200, settings]
    if (method === 'POST' && path.startsWith('/api/positions/')) return [200, settings.positions[0]]
    if (method === 'POST' && path === '/api/locations/l1/supplements') return [201, night]
    if (method === 'PATCH') return [200, night]
    if (method === 'DELETE') return [204, null]
    return [404, { detail: 'Nie ma.' }]
  })
  renderScreen(
    <AsManager>
      <PaySection locationId="l1" today={today} />
    </AsManager>,
  )
  return calls
}

describe('PaySection', () => {
  it('shows the rate of today and the raise ahead, and changes a rate from a day', async () => {
    const calls = show()
    const seller = (await screen.findByText('Sprzedawca')).closest('li')!
    expect(seller).toHaveTextContent(/31,40\szł\/h/)
    expect(seller).toHaveTextContent(/Od 1 stycznia 2027: 33,00\szł\/h/)
    expect(screen.getByText(/stawki: 1 z 2, dodatki: 1/)).toBeInTheDocument()

    fireEvent.click(within(seller).getByRole('button', { name: 'Zmień stawkę: Sprzedawca' }))
    fireEvent.change(within(seller).getByLabelText('Stawka, zł/h'), { target: { value: '32,50' } })
    expect(within(seller).getByLabelText('Od dnia')).toHaveValue('2026-11-22')
    fireEvent.change(within(seller).getByLabelText('Od dnia'), { target: { value: '2026-12-01' } })
    fireEvent.click(within(seller).getByRole('button', { name: 'Zapisz stawkę' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')).toMatchObject({
        url: '/api/positions/p1/rates',
        body: { hourly_rate: 32.5, valid_from: '2026-12-01' },
      }),
    )
  })

  it('warns when a rate change or a removed step reaches months that have passed', async () => {
    const calls = show()
    const seller = (await screen.findByText('Sprzedawca')).closest('li')!
    fireEvent.click(within(seller).getByRole('button', { name: 'Zmień stawkę: Sprzedawca' }))
    expect(within(seller).queryByText('To zmieni wypłatę za minione miesiące.')).not.toBeInTheDocument()
    fireEvent.change(within(seller).getByLabelText('Od dnia'), { target: { value: '2026-10-15' } })
    expect(within(seller).getByText('To zmieni wypłatę za minione miesiące.')).toBeInTheDocument()
    fireEvent.click(within(seller).getByRole('button', { name: 'Anuluj' }))

    fireEvent.click(within(seller).getByText('Zmiany stawki (2)'))
    fireEvent.click(within(seller).getByRole('button', { name: 'Usuń stawkę Sprzedawca od 1 stycznia 2027' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'DELETE')?.url).toBe('/api/position-rates/r2'))
    fireEvent.click(within(seller).getByRole('button', { name: 'Usuń stawkę Sprzedawca od początku' }))
    expect(await screen.findByRole('dialog', { name: 'Usunąć stawkę od początku?' })).toHaveTextContent(
      'To zmieni wypłatę za minione miesiące.',
    )
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Tak, usuń stawkę' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.url)).toContain('/api/position-rates/r1'))
  })

  it('saves the first rate of a position for every shift and catches a typo', async () => {
    const calls = show()
    const baker = (await screen.findByText('Piekarz')).closest('li')!
    expect(baker).toHaveTextContent('bez stawki')
    fireEvent.click(within(baker).getByRole('button', { name: 'Zmień stawkę: Piekarz' }))
    expect(within(baker).queryByLabelText('Od dnia')).not.toBeInTheDocument()
    expect(within(baker).getByText('Pierwsza stawka liczy się dla wszystkich zmian.')).toBeInTheDocument()
    fireEvent.change(within(baker).getByLabelText('Stawka, zł/h'), { target: { value: 'dużo' } })
    fireEvent.click(within(baker).getByRole('button', { name: 'Zapisz stawkę' }))
    expect(within(baker).getByText('Wpisz stawkę w złotych, np. 31,40.')).toBeInTheDocument()
    fireEvent.change(within(baker).getByLabelText('Stawka, zł/h'), { target: { value: '36' } })
    fireEvent.click(within(baker).getByRole('button', { name: 'Zapisz stawkę' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ hourly_rate: 36, valid_from: null }),
    )
  })

  it('lists supplements in words, keeps ended ones apart, and changes one from a day', async () => {
    const calls = show()
    const item = (await screen.findByText('Noc')).closest('li')!
    expect(item).toHaveTextContent(/22:00–6:00 · codziennie · \+6,00\szł\/h · wszystkie stanowiska/)
    expect(screen.getByText('Zakończone dodatki (1)')).toBeInTheDocument()
    const sunday = screen.getByText('Niedziela').closest('li')!
    expect(sunday).toHaveTextContent('cała doba · niedz · +50% stawki · Piekarz')
    expect(sunday).toHaveTextContent('do 31 października 2026')

    fireEvent.click(within(item).getByRole('button', { name: 'Zmień dodatek Noc' }))
    fireEvent.change(within(item).getByLabelText('Kwota, zł/h'), { target: { value: '8' } })
    expect(within(item).getByLabelText('Zmiana od dnia')).toHaveValue('2026-11-22')
    fireEvent.click(within(item).getByRole('button', { name: 'Zapisz dodatek' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({
        url: '/api/supplements/n1',
        body: { name: 'Noc', start_time: '22:00', end_time: '06:00', value: 8, change_from: '2026-11-22' },
      }),
    )
  })

  it('adds a supplement for chosen days and positions, and ends one from a day', async () => {
    const calls = show()
    fireEvent.click(await screen.findByRole('button', { name: 'Dodaj dodatek' }))
    fireEvent.change(screen.getByLabelText('Nazwa'), { target: { value: 'Weekend' } })
    fireEvent.click(screen.getByLabelText('Cała doba'))
    for (const day of ['pon', 'wt', 'śr', 'czw', 'pt']) fireEvent.click(screen.getByLabelText(day))
    fireEvent.change(screen.getByLabelText('Dodatek'), { target: { value: 'percent' } })
    fireEvent.change(screen.getByLabelText('Procent'), { target: { value: '20' } })
    fireEvent.click(screen.getByLabelText('Wszystkie stanowiska'))
    fireEvent.click(screen.getByRole('button', { name: 'Dodaj dodatek' }))
    expect(screen.getByText('Wybierz stanowiska, których dotyczy dodatek.')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Piekarz'))
    fireEvent.click(screen.getByRole('button', { name: 'Dodaj dodatek' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
        name: 'Weekend',
        start_time: '00:00',
        end_time: '00:00',
        weekdays: [5, 6],
        kind: 'percent',
        value: 20,
        all_positions: false,
        position_ids: ['p2'],
        valid_from: null,
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Zakończ dodatek Noc' }))
    fireEvent.change(await screen.findByLabelText('Bez dodatku od dnia'), { target: { value: '2026-12-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tak, zakończ dodatek' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'DELETE')?.url).toBe('/api/supplements/n1?end_from=2026-12-01'))
  })
})

describe('OwnRates', () => {
  it('shows the position’s rate as the fallback and gives a person a raise from a day', async () => {
    const calls = mockApi((method, path) => {
      if (path === '/api/locations/l1/pay-settings') return [200, settings]
      if (path === '/api/locations/l1/personal-rates') {
        return [200, [{ id: 'o1', employee_id: 'e1', position_id: 'p1', valid_from: '2026-11-01', hourly_rate: 35 }]]
      }
      if (method === 'POST') return [200, []]
      return [404, { detail: 'Nie ma.' }]
    })
    renderScreen(
      <AsManager>
        <OwnRates employeeId="e1" positionIds={['p1', 'p2']} locationId="l1" today={today} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByText('Stawki'))
    expect(await screen.findByText('własna: 1')).toBeInTheDocument()
    const seller = (await screen.findByText('Sprzedawca')).closest('li')!
    expect(seller).toHaveTextContent(/35,00\szł\/h/)
    const baker = screen.getByText('Piekarz').closest('li')!
    expect(baker).toHaveTextContent('stawka stanowiska (bez stawki)')
    fireEvent.click(within(baker).getByRole('button', { name: 'Zmień stawkę: Piekarz' }))
    expect(within(baker).getByLabelText('Od dnia')).toHaveValue('2026-11-22')
    expect(within(baker).queryByText('Pierwsza stawka liczy się dla wszystkich zmian.')).not.toBeInTheDocument()
    fireEvent.click(within(baker).getByRole('button', { name: 'Anuluj' }))

    fireEvent.click(within(seller).getByRole('button', { name: 'Zmień stawkę: Sprzedawca' }))
    expect(within(seller).getByText('Puste pole: znowu stawka stanowiska.')).toBeInTheDocument()
    fireEvent.change(within(seller).getByLabelText('Stawka, zł/h'), { target: { value: '38' } })
    fireEvent.change(within(seller).getByLabelText('Od dnia'), { target: { value: '2027-03-01' } })
    fireEvent.click(within(seller).getByRole('button', { name: 'Zapisz stawkę' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')).toMatchObject({
        url: '/api/employees/e1/rates',
        body: { hourly_rate: 38, valid_from: '2027-03-01', position_id: 'p1' },
      }),
    )
  })
})
