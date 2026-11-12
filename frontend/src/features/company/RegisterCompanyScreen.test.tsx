import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { RegisterCompanyScreen } from './RegisterCompanyScreen'

const me = { id: 'u1', phone: '+48500100100', first_name: '', last_name: '', companies: [], pending_invitations: 0 }

describe('RegisterCompanyScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('creates a company without a code and says it gets 14 days to try', async () => {
    const calls = mockApi(() => [201, { id: 'c9', name: 'Pod Lipą', role: 'owner', read_only: false, trial: true }])
    const onCreated = vi.fn()
    renderScreen(<RegisterCompanyScreen me={me} onCreated={onCreated} />)
    expect(await screen.findByText(/Bez kodu masz 14 dni na wypróbowanie wszystkiego/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Załóż firmę' })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Nazwa firmy'), { target: { value: 'Pod Lipą' } })
    fireEvent.change(screen.getByLabelText('Twoje imię'), { target: { value: 'Ewa' } })
    fireEvent.click(submit)
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('c9'))
    expect(calls[0]).toMatchObject({
      url: '/api/companies',
      method: 'POST',
      body: { name: 'Pod Lipą', first_name: 'Ewa', last_name: '', code: '' },
    })
  })

  it('shows the reason when the company cannot be created', async () => {
    mockApi(() => [400, { detail: 'Ten kod nie istnieje albo został już wykorzystany.' }])
    renderScreen(<RegisterCompanyScreen me={me} onCreated={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('Nazwa firmy'), { target: { value: 'Pod Lipą' } })
    fireEvent.change(screen.getByLabelText('Kod dostępu (jeśli masz)'), { target: { value: 'zly-kod' } })
    fireEvent.click(screen.getByRole('button', { name: 'Załóż firmę' }))
    expect(await screen.findByText('Ten kod nie istnieje albo został już wykorzystany.')).toBeInTheDocument()
  })
})
