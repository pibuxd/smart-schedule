import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { LocationSettingsScreen } from './SettingsScreen'
import { StaffingCalendar } from './StaffingCalendar'
import { AsManager } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

it('keeps each weekday’s hours and experience quota when saving the staffing form', async () => {
  const base = { shift_type_id: 's', position_id: 'p', count: 3 }
  const monday = { ...base, weekday: 0, experienced: 0, start_time: '06:00:00', end_time: '08:00:00' }
  const saturday = { ...base, weekday: 5, experienced: 2, start_time: '10:00:00', end_time: '12:00:00' }
  const setup = {
    positions: [{ id: 'p', name: 'Kasa', employees: 1 }],
    shift_types: [{ id: 's', name: 'Dostawa', kind: 'flexible', start_time: null, end_time: null }],
    staffing: [monday, saturday], closures: [], exceptions: [], arranged: [],
  }
  const calls = mockApi((_method, path) => {
    if (path.endsWith('/setup') || path.endsWith('/staffing')) return [200, setup]
    if (path.endsWith('/overview')) return [200, { groups: [] }]
    return [200, { id: 'l', name: 'Lokal', address: '', schedule_period: 'month', availability_deadline_days: 7 }]
  })
  renderScreen(<AsManager><LocationSettingsScreen locationId="l" /></AsManager>)

  fireEvent.click(await screen.findByRole('button', { name: 'Zapisz obsadę' }))
  await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ cells: [monday, saturday] }))
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Dostawa, Kasa, sob: w tym doświadczonych' }), { target: { value: '1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Zapisz obsadę' }))
  await waitFor(() => expect(calls.filter((c) => c.method === 'PUT')[1]?.body)
    .toEqual({ cells: [monday, { ...saturday, experienced: 1 }] }))
})

it('shows each day’s staffing in a calendar and saves one day with other numbers', async () => {
  const cell = { shift_type_id: 's', position_id: 'p', experienced: 0, start_time: null, end_time: null }
  const setup = {
    positions: [{ id: 'p', name: 'Kasa', employees: 1 }],
    shift_types: [{ id: 's', name: 'Ranna', kind: 'fixed', start_time: '06:00:00', end_time: '14:00:00' }],
    staffing: [0, 1, 2, 3, 4].map((weekday) => ({ ...cell, weekday, count: 2 })),
    exceptions: [{ ...cell, id: 'x', date: '2026-12-24', count: 1, note: 'Wigilia' }],
    closures: [{ id: 'c', date: '2026-12-25', note: 'Boże Narodzenie', in_draft: false, in_published: false }],
    arranged: [{ start: '2026-12-21', end: '2026-12-27' }],
  }
  const calls = mockApi((_method, path) => {
    if (path.endsWith('/setup') || path.includes('/staffing-days/')) return [200, setup]
    if (path.endsWith('/overview')) return [200, { groups: [] }]
    return [200, { id: 'l', name: 'Lokal', address: '', schedule_period: 'month', availability_deadline_days: 7 }]
  })
  renderScreen(<AsManager><StaffingCalendar locationId="l" setup={setup as never} today={new Date(2026, 11, 1)} /></AsManager>)

  expect(await screen.findByRole('heading', { name: 'Grudzień 2026' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'czwartek 24 grudnia: 1 os., inaczej niż zwykle' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'piątek 25 grudnia: lokal zamknięty' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'środa 23 grudnia: 2 os.' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Więcej osób: Ranna, Kasa' }))
  expect(screen.getByText(/Ten dzień jest już w ułożonym grafiku/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Zapisz obsadę dnia' }))
  await waitFor(() => expect(calls.find((c) => c.method === 'PUT')).toMatchObject({
    url: '/api/locations/l/staffing-days/2026-12-23',
    body: { cells: [{ shift_type_id: 's', position_id: 'p', count: 3, experienced: 0, start_time: null, end_time: null }], note: '' },
  }))

  fireEvent.click(screen.getByRole('button', { name: 'czwartek 24 grudnia: 1 os., inaczej niż zwykle' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Wróć do zwykłej obsady' }))
  await waitFor(() => expect(calls.filter((c) => c.method === 'PUT')[1]?.body).toEqual({ cells: [], note: '' }))
})
