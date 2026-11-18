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
  position_experience: [{ position_id: 'p1', experience }],
  max_hours_month: null,
  target_hours_month: null,
  is_active: true,
  is_manager: false,
  draft_shifts: 0,
})

const setup = { positions: [{ id: 'p1', name: 'Kelner', employees: 2 }], shift_types: [], staffing: [], exceptions: [], closures: [] }

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

  it('lets the manager set another level on one position', async () => {
    const two = {
      ...person('e1', 'Ala', 3),
      position_ids: ['p1', 'p2'],
      position_experience: [
        { position_id: 'p1', experience: 3 },
        { position_id: 'p2', experience: 1 },
      ],
    }
    const positions = [...setup.positions, { id: 'p2', name: 'Barista', employees: 1 }]
    const calls = mockApi((method, path) => {
      if (path.endsWith('/employees')) return [200, [two]]
      if (path.endsWith('/setup')) return [200, { ...setup, positions }]
      if (path.endsWith('/invitations')) return [200, []]
      if (method === 'PATCH') return [200, two]
      return [404, { detail: 'Nie ma' }]
    })
    renderScreen(
      <AsManager>
        <EmployeesScreen locationId="l1" />
      </AsManager>,
    )
    expect(await screen.findByText('Barista: początkujący')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Zmień: Ala Nowak' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByRole('combobox', { name: 'Stopień na stanowisku Barista' })).toHaveValue('1')
    fireEvent.change(within(sheet).getByRole('combobox', { name: 'Stopień na stanowisku Kelner' }), {
      target: { value: '2' },
    })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz' }))

    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const body = calls.find((c) => c.method === 'PATCH')!.body as { position_experience: unknown }
    expect(body.position_experience).toEqual([
      { position_id: 'p1', experience: 2 },
      { position_id: 'p2', experience: 1 },
    ])
  })

  it('lets a manager who also works shifts add themselves with one button', async () => {
    let added = false
    const me = { ...person('e9', 'Teresa', 2), phone: '+48500100100', is_manager: true }
    const calls = mockApi((method, path) => {
      if (path === '/api/me') return [200, { id: 'u1', phone: '+48500100100', first_name: 'Teresa', last_name: 'Nowak', companies: [], pending_invitations: 0 }]
      if (method === 'POST' && path.endsWith('/employees/me')) {
        added = true
        return [200, me]
      }
      if (path.endsWith('/employees')) return [200, added ? [person('e1', 'Ala', 1), me] : [person('e1', 'Ala', 1)]]
      if (path.endsWith('/setup')) return [200, setup]
      if (path.endsWith('/invitations')) return [200, []]
      return [404, { detail: 'Nie ma' }]
    })
    renderScreen(
      <AsManager>
        <EmployeesScreen locationId="l1" />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Dodaj mnie jako pracownika' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/locations/l1/employees/me')).toBe(true))
    expect(await screen.findByText('Teresa Nowak')).toBeInTheDocument()
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Dodaj mnie jako pracownika' })).not.toBeInTheDocument())
  })

  it('corrects the name, and warns about shifts in the draft before switching someone off', async () => {
    const calls = mockApi((method, path) => {
      if (path.endsWith('/employees')) return [200, [{ ...person('e1', 'Ala', 2), draft_shifts: 8, revision: 'initial' }]]
      if (path.endsWith('/setup')) return [200, setup]
      if (path.endsWith('/invitations')) return [200, []]
      if (method === 'PATCH') return [200, person('e1', 'Alicja', 2)]
      return [404, { detail: 'Nie ma' }]
    })
    renderScreen(
      <AsManager>
        <EmployeesScreen locationId="l1" />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Zmień: Ala Nowak' }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.change(within(sheet).getByLabelText('Imię'), { target: { value: 'Alicja' } })
    fireEvent.click(within(sheet).getByRole('checkbox', { name: /W grafiku/ }))
    expect(within(sheet).getByRole('alert')).toHaveTextContent('Ta osoba ma 8 zmian w szkicu grafiku.')
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz' }))

    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>
    expect(body).toEqual({ first_name: 'Alicja', is_active: false, revision: 'initial', location_id: 'l1' })
    expect(body).not.toHaveProperty('phone') // the login number is changed only by the superadmin
  })

  it('shows the main location of someone from another location and does not offer switching them off', async () => {
    const guest = { ...person('e3', 'Kasia', 2), is_home: false, home_location_name: 'Rynek' }
    const calls = mockApi((method, path) => {
      if (path.endsWith('/employees')) return [200, [guest]]
      if (path.endsWith('/setup')) return [200, setup]
      if (path.endsWith('/invitations')) return [200, []]
      if (method === 'PATCH') return [200, guest]
      return [404, { detail: 'Nie ma' }]
    })
    renderScreen(
      <AsManager>
        <EmployeesScreen locationId="l1" />
      </AsManager>,
    )
    expect(await screen.findByText('Lokal główny: Rynek')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Zmień: Kasia Nowak' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).queryByRole('checkbox', { name: /W grafiku/ })).not.toBeInTheDocument()
    expect(within(sheet).getByText(/Wyłączyć ją z grafiku może kierownik lokalu głównego/)).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('radio', { name: /Doświadczony/ }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz' }))

    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>
    expect(body.location_id).toBe('l1')
  })
})
