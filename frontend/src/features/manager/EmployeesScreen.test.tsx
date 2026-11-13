import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { EmployeesScreen } from './EmployeesScreen'
import { AsManager } from './test-utils'

const person = (id: string, first: string, experience: 1 | 2 | 3) => ({
  id,
  first_name: first,
  last_name: 'Nowak',
  phone: '+48600100001',
  position_ids: ['p1'],
  experience,
  max_hours_month: null,
  target_hours_month: null,
  is_active: true,
  is_manager: false,
})

const setup = { positions: [{ id: 'p1', name: 'Kelner', employees: 2 }], shift_types: [], staffing: [], exceptions: [] }

describe('EmployeesScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the experience label and lets the manager change it', async () => {
    const calls = mockApi((method, path) => {
      if (path.endsWith('/employees')) return [200, [person('e1', 'Ala', 1), person('e2', 'Ola', 3)]]
      if (path.endsWith('/setup')) return [200, setup]
      if (path.endsWith('/invitations')) return [200, []]
      if (method === 'PATCH') return [200, person('e1', 'Ala', 2)]
      return [404, { detail: 'Nie ma' }]
    })
    renderScreen(
      <AsManager>
        <EmployeesScreen locationId="l1" />
      </AsManager>,
    )
    expect(await screen.findByText('Początkujący')).toBeInTheDocument()
    expect(screen.getByText('Doświadczony')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Zmień: Ala Nowak' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByRole('radio', { name: /Początkujący/ })).toBeChecked()
    fireEvent.click(within(sheet).getByRole('radio', { name: /Samodzielny/ }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz' }))

    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.url).toBe('/api/employees/e1')
    expect((patch.body as { experience: number }).experience).toBe(2)
  })
})
