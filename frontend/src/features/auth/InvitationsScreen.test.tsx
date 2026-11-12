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

describe('InvitationsScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks once more before declining', async () => {
    const calls = mockApi((method) => (method === 'GET' ? [200, [invitation]] : [200, invitation]))
    renderScreen(<InvitationsScreen name="Halina Olszewska" />)
    expect(await screen.findByText('Teresa Gawlik')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Odrzucam' }))
    expect(screen.getByText(/Na pewno odrzucić/)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Tak, odrzucam' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/invitations/i1/decline')).toBe(true))
  })

  it('has an empty state', async () => {
    mockApi(() => [200, []])
    renderScreen(<InvitationsScreen name="" />)
    expect(await screen.findByText('Nie masz żadnych zaproszeń')).toBeInTheDocument()
  })
})
