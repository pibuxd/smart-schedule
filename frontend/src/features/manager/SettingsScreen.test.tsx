import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { LocationSettingsScreen } from './SettingsScreen'
import { AsManager } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

it('keeps each weekday’s hours and experience quota when saving the staffing form', async () => {
  const base = { shift_type_id: 's', position_id: 'p', count: 3 }
  const monday = { ...base, weekday: 0, experienced: 0, start_time: '06:00:00', end_time: '08:00:00' }
  const saturday = { ...base, weekday: 5, experienced: 2, start_time: '10:00:00', end_time: '12:00:00' }
  const setup = {
    positions: [{ id: 'p', name: 'Kasa', employees: 1 }],
    shift_types: [{ id: 's', name: 'Dostawa', kind: 'flexible', start_time: null, end_time: null }],
    staffing: [monday, saturday], closures: [], exceptions: [],
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
