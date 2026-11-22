import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { HoursScreen } from './HoursScreen'
import { AsManager } from './test-utils'

const change = (over = {}) => ({
  id: 'h1',
  status: 'pending',
  employee_id: 'e1',
  employee_name: 'Anna Wróbel',
  location_id: 'l1',
  location_name: 'Rynek',
  position_name: 'Sprzedawca',
  date: '2026-11-20',
  planned_start_time: '06:00',
  planned_end_time: '14:00',
  planned_hours: 8,
  start_time: '06:00',
  end_time: '15:30',
  hours: 9.5,
  difference_minutes: 90,
  reason: 'Inwentaryzacja',
  by_manager: false,
  created_at: '2026-11-20T15:00:00Z',
  decided_at: null,
  decided_by_name: '',
  assignment_id: 'as1',
  ...over,
})

const report = (rows: unknown[] = [], pay: number | null = null) => ({
  month: '2026-11',
  locations: [{ id: 'l1', name: 'Rynek' }],
  rows,
  total: 0,
  latest_month: null,
  pay,
  unpriced_hours: 0,
})

const row = (over = {}) => ({
  employee_id: 'e1',
  name: 'Anna Wróbel',
  home_location_name: 'Rynek',
  shifts: 10,
  total: 81.5,
  longer: 1.5,
  shorter: 0,
  by_location: [{ location_id: 'l1', hours: 81.5 }],
  elsewhere: false,
  ...over,
})

const handoverShift = (over = {}) => ({
  id: 'as1',
  version_id: 'v1',
  shift: {
    date: '2026-11-20',
    start_time: '06:00',
    end_time: '14:00',
    hours: 8,
    location_id: 'l1',
    location_name: 'Rynek',
    position_name: 'Sprzedawca',
    shift_type_name: 'Ranna',
  },
  employee_id: 'e1',
  employee_name: 'Anna Wróbel',
  started: true,
  offer_id: null,
  worked: null,
  hours_report: null,
  ...over,
})

function api({
  pending = [change()],
  recent = [] as unknown[],
  rows = [row()],
  pay = null as number | null,
} = {}) {
  return mockApi((method, path) => {
    if (path === '/api/manager/hours-changes') return [200, { pending, recent, waiting: pending.length }]
    if (method === 'POST' && path.endsWith('/approve')) return [200, change({ status: 'approved' })]
    if (method === 'POST' && path.endsWith('/reject')) return [200, change({ status: 'rejected' })]
    if (method === 'POST' && path === '/api/assignments/as1/hours')
      return [200, { assignment_id: 'as1', planned_start_time: '06:00', planned_end_time: '14:00', worked: null }]
    if (path === '/api/reports/hours') return [200, report(rows, pay)]
    if (path === '/api/manager/overview') return [200, { locations: [{ id: 'l1', name: 'Rynek' }] }]
    if (path === '/api/locations/l1/handover-shifts') return [200, [handoverShift()]]
    return [404, { detail: 'Nie ma.' }]
  })
}

function show(readOnly = false) {
  renderScreen(
    <AsManager readOnly={readOnly}>
      <HoursScreen today={new Date(2026, 10, 21)} />
    </AsManager>,
  )
}

describe('HoursScreen: other hours', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists a waiting report with its reason and approves it', async () => {
    const calls = api()
    show()
    const item = (await screen.findByText('Anna Wróbel', { selector: 'b' })).closest('li')!
    expect(item).toHaveTextContent('6:00–15:30 zamiast 6:00–14:00: nadgodziny: +1 h 30 min')
    expect(item).toHaveTextContent('Powód: Inwentaryzacja')
    fireEvent.click(within(item).getByRole('button', { name: 'Zatwierdź: Anna Wróbel' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/hours-changes/h1/approve')).toBe(true))
  })

  it('rejects a report, and shows decisions in a fold', async () => {
    const calls = api({ recent: [change({ id: 'h0', status: 'rejected', decided_by_name: 'Menedżer', date: '2026-11-18' })] })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Odrzuć: Anna Wróbel' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/hours-changes/h1/reject')).toBe(true))
    fireEvent.click(screen.getByText('Ostatnie decyzje'))
    expect(await screen.findByText('Odrzucone (Menedżer)')).toBeInTheDocument()
  })

  it('says when nobody waits and shows overtime in the table only when there is some', async () => {
    api({ pending: [] })
    show()
    expect(await screen.findByText('Nikt nie czeka na decyzję o godzinach.')).toBeInTheDocument()
    expect(await screen.findByRole('columnheader', { name: 'Nadgodziny' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '+1,5' })).toBeInTheDocument()
    expect(screen.getByText(/nie nadgodziny z Kodeksu pracy/)).toBeInTheDocument()
  })

  it('keeps the table short without other hours', async () => {
    api({ pending: [], rows: [row({ longer: 0, shorter: 0 })] })
    show()
    await screen.findByRole('columnheader', { name: 'Razem godzin' })
    expect(screen.queryByRole('columnheader', { name: 'Nadgodziny' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Kodeksu pracy/)).not.toBeInTheDocument()
  })

  it('shows the estimated pay per person and in total once there are rates', async () => {
    api({
      pending: [],
      rows: [
        row({ longer: 0, pay: 2559.1, unpriced_hours: 0 }),
        row({ employee_id: 'e2', name: 'Ewa Nowak', longer: 0, pay: null, unpriced_hours: 16, total: 16 }),
      ],
      pay: 2559.1,
    })
    show()
    expect(await screen.findByRole('columnheader', { name: 'Wypłata' })).toBeInTheDocument()
    const anna = screen.getByText('Anna Wróbel', { selector: 'span' }).closest('tr')!
    expect(anna).toHaveTextContent(/2559,10\szł/)
    const ewa = screen.getByText('Ewa Nowak').closest('tr')!
    expect(ewa).toHaveTextContent('–16 h bez stawki')
    expect(screen.getByText('Razem').closest('tr')).toHaveTextContent(/2559,10\szł/)
    expect(screen.getByText(/Wypłata to szacunek brutto/)).toBeInTheDocument()
    expect(screen.queryByText(/Wpisz stawki przy stanowiskach/)).not.toBeInTheDocument()
  })

  it('says where to set rates when no shift has one', async () => {
    api({ pending: [], rows: [row({ longer: 0 })] })
    show()
    await screen.findByRole('columnheader', { name: 'Razem godzin' })
    expect(screen.queryByRole('columnheader', { name: 'Wypłata' })).not.toBeInTheDocument()
    expect(screen.getByText(/Wpisz stawki przy stanowiskach w ustawieniach lokalu/)).toBeInTheDocument()
  })

  it('lets the manager set the hours of a published shift alone', async () => {
    const calls = api({ pending: [] })
    show()
    fireEvent.click(await screen.findByText('Zmień godziny sam'))
    fireEvent.click(await screen.findByRole('button', { name: 'Zmień godziny: Anna Wróbel' }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.change(within(sheet).getByLabelText('Do'), { target: { value: '12:00' } })
    fireEvent.change(within(sheet).getByLabelText('Powód (nie musisz pisać)'), { target: { value: 'źle się czuła' } })
    expect(within(sheet).getByRole('status')).toHaveTextContent('Krócej o 2 h')
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz godziny' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/assignments/as1/hours')?.body).toEqual({
        employee_id: 'e1',
        start_time: '06:00',
        end_time: '12:00',
        reason: 'źle się czuła',
      }),
    )
  })

  it('reaches older shifts month by month', async () => {
    const calls = api({ pending: [] })
    show()
    fireEvent.click(await screen.findByText('Zmień godziny sam'))
    await screen.findByRole('button', { name: 'Zmień godziny: Anna Wróbel' })
    fireEvent.click(screen.getByRole('button', { name: 'Zmiany z poprzedniego miesiąca' }))
    const now = new Date()
    const before = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    const month = `${before.getFullYear()}-${String(before.getMonth() + 1).padStart(2, '0')}`
    await waitFor(() =>
      expect(calls.some((c) => c.url === `/api/locations/l1/handover-shifts?month=${month}`)).toBe(true),
    )
  })

  it('cannot decide in read-only mode', async () => {
    api()
    show(true)
    expect(await screen.findByRole('button', { name: 'Zatwierdź: Anna Wróbel' })).toBeDisabled()
  })
})
