import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { EmployeesScreen } from './EmployeesScreen'
import { AsManager } from './test-utils'
import { persons } from './words'

const setup = { positions: [{ id: 'p1', name: 'Kasa', employees: 0 }], shift_types: [], staffing: [], exceptions: [], closures: [], arranged: [] }
const listed = (first: string, phone: string, problem: string | null = null, position_ids: string[] = []) => ({
  first_name: first,
  last_name: 'Nowak',
  phone,
  position_ids,
  location_id: 'l1',
  unknown_positions: [],
  problem,
})

function screenWith(answer: Parameters<typeof mockApi>[0]) {
  const calls = mockApi((method, path, body) => {
    if (path.endsWith('/employees')) return [200, []]
    if (path.endsWith('/setup')) return [200, setup]
    if (path.endsWith('/l1/invitations')) return [200, []]
    return answer(method, path, body)
  })
  renderScreen(
    <AsManager>
      <EmployeesScreen locationId="l1" />
    </AsManager>,
  )
  return calls
}

describe('Zaproś kilka osób', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads a pasted list, lets the manager fix a person and invites the ready ones', async () => {
    const calls = screenWith((_method, path, body) => {
      if (path.endsWith('/invitations/read')) {
        expect((body as { text: string }).text).toContain('Anna')
        return [200, { people: [listed('Anna', '+48512345678', null, ['p1']), listed('Jan', '123', 'Podaj polski numer telefonu (+48).')], skipped_lines: 1 }]
      }
      if (path.endsWith('/invitations/many')) {
        const people = (body as { people: { phone: string }[] }).people
        return [200, { invited: people.map((p, i) => ({ id: `i${i}`, location_id: 'l1', phone: p.phone, first_name: '', last_name: '', role: 'employee', status: 'pending', position_ids: [], created_at: '', decided_at: null })), skipped: [] }]
      }
      return [404, { detail: 'Nie ma' }]
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Zaproś kilka osób' }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.change(within(sheet).getByLabelText('Wklej listę'), { target: { value: 'Anna Nowak 512 345 678\nJan 123' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Sprawdź listę' }))

    expect(await within(sheet).findByText('Na liście: 2 osoby. Do poprawienia: 1.')).toBeInTheDocument()
    expect(within(sheet).getByText('+48 512 345 678')).toBeInTheDocument()
    expect(within(sheet).getByText('Kasa')).toBeInTheDocument()
    expect(within(sheet).getByRole('alert')).toHaveTextContent('Podaj polski numer telefonu (+48).')
    expect(within(sheet).getByText('Pominięte wiersze bez numeru telefonu: 1.')).toBeInTheDocument()

    // Only Anna is ready; Jan is fixed by hand and goes too.
    expect(within(sheet).getByRole('button', { name: 'Zaproś 1 osobę' })).toBeEnabled()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Popraw: Jan Nowak' }))
    fireEvent.change(within(sheet).getByLabelText('Numer telefonu'), { target: { value: '600 100 200' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zaproś 2 osoby' }))

    expect(await within(sheet).findByText(/Zaproszono 2 osoby/)).toBeInTheDocument()
    const sent = calls.find((c) => c.url.endsWith('/invitations/many'))!.body as { people: { phone: string; position_ids: string[] }[] }
    expect(sent.people.map((p) => p.phone)).toEqual(['+48512345678', '600 100 200'])
    expect(sent.people[0].position_ids).toEqual(['p1'])
    expect(within(sheet).getByRole('button', { name: 'Gotowe' })).toBeInTheDocument()
  })

  it('reads numbers without a code as the chosen country', async () => {
    const calls = screenWith((_method, path) => {
      if (path.endsWith('/invitations/read')) return [200, { people: [listed('Olena', '+380501234567')], skipped_lines: 0 }]
      if (path.endsWith('/invitations/many')) return [200, { invited: [], skipped: [] }]
      return [404, { detail: 'Nie ma' }]
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Zaproś kilka osób' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByLabelText('Numery bez kierunkowego są z kraju')).toHaveValue('PL')
    fireEvent.change(within(sheet).getByLabelText('Numery bez kierunkowego są z kraju'), { target: { value: 'UA' } })
    fireEvent.change(within(sheet).getByLabelText('Wklej listę'), { target: { value: 'Olena Nowak 501234567' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Sprawdź listę' }))

    expect(await within(sheet).findByText('+380 501 234 567')).toBeInTheDocument()
    expect(within(sheet).getByText('Numery bez kierunkowego czytam jako: Ukraina +380.')).toBeInTheDocument()
    expect((calls.find((c) => c.url.endsWith('/invitations/read'))!.body as { region: string }).region).toBe('UA')
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zaproś 1 osobę' }))
    await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith('/invitations/many'))).toBe(true))
    expect((calls.find((c) => c.url.endsWith('/invitations/many'))!.body as { region: string }).region).toBe('UA')
  })

  it('sends a chosen file and shows why it could not be read', async () => {
    const calls = screenWith((_method, path) => {
      if (path.endsWith('/invitations/read')) return [400, { detail: 'To stary plik Excela (.xls). Zapisz go jako .xlsx albo CSV i wgraj jeszcze raz.' }]
      return [404, { detail: 'Nie ma' }]
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Zaproś kilka osób' }))
    const sheet = await screen.findByRole('dialog')
    const file = new File(['...'], 'lista.xls')
    fireEvent.change(within(sheet).getByLabelText('Plik z listą osób'), { target: { files: [file] } })

    expect(await within(sheet).findByText(/stary plik Excela/)).toBeInTheDocument()
    expect((calls.find((c) => c.url.endsWith('/invitations/read'))!.body as { file: File }).file.name).toBe('lista.xls')
  })

  it('counts people in Polish', () => {
    expect([1, 2, 5, 12, 22, 25].map((n) => persons(n))).toEqual(['1 osobę', '2 osoby', '5 osób', '12 osób', '22 osoby', '25 osób'])
  })
})
