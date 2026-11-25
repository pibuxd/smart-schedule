import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { InvitationsScreen } from './InvitationsScreen'

const invitation = {
  id: 'i1',
  company_name: 'Piekarnia Złoty Kłos',
  location_name: 'Wieliczka – Rynek',
  location_address: 'Rynek Górny 4',
  role: 'employee',
  invited_by_name: 'Teresa Gawlik',
  created_at: '2026-11-12T10:00:00Z',
}

const me = { id: 'u1', phone: '+48510000001', first_name: '', last_name: '', companies: [], pending_invitations: 0 }
const halina = { ...me, first_name: 'Halina', last_name: 'Olszewska' }
const company = { id: 'c1', name: 'Złoty Kłos', role: 'employee' as const, read_only: false, works_shifts: true }

describe('InvitationsScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks once more before declining', async () => {
    const calls = mockApi((method) => (method === 'GET' ? [200, [invitation]] : [200, invitation]))
    renderScreen(<InvitationsScreen me={halina} />)
    expect(await screen.findByText('Teresa Gawlik')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Odrzucam' }))
    expect(screen.getByText(/Na pewno odrzucić/)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Tak, odrzucam' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/invitations/i1/decline')).toBe(true))
  })

  it('has an empty state that names the number and has no way back to a schedule without a company', async () => {
    mockApi(() => [200, []])
    renderScreen(<InvitationsScreen me={me} />)
    expect(await screen.findByText('Nie masz żadnych zaproszeń')).toBeInTheDocument()
    expect(screen.getAllByText('+48 510 000 001')).toHaveLength(2)
    expect(screen.queryByRole('link', { name: 'Wróć do grafiku' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Prowadzisz lokal? Załóż firmę' })).toBeInTheDocument()
  })

  it('leads back to the schedule when the person already works somewhere', async () => {
    mockApi(() => [200, []])
    renderScreen(<InvitationsScreen me={{ ...halina, companies: [company] }} />)
    expect(await screen.findByRole('link', { name: 'Wróć do grafiku' })).toBeInTheDocument()
    expect(screen.getByText('Halina Olszewska')).toBeInTheDocument()
  })

  it('logs out without a company', async () => {
    const calls = mockApi((method) => (method === 'POST' ? [204, null] : [200, []]))
    renderScreen(<InvitationsScreen me={me} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Wyloguj' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/auth/logout')).toBe(true))
  })
})
