import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { AccessScreen } from './AccessScreen'
import { AsManager } from './test-utils'

const trial = {
  source: 'trial',
  trial: true,
  starts_at: '2026-11-12T10:00:00+01:00',
  ends_at: '2026-11-26T10:00:00+01:00',
  days_left: 14,
  read_only: false,
  expiring_soon: false,
  generations_used: 2,
  generations_limit: 20,
}

describe('AccessScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the trial and redeems a code', async () => {
    const calls = mockApi((method) =>
      method === 'POST' ? [200, { ...trial, source: 'code', trial: false, days_left: 44 }] : [200, trial],
    )
    renderScreen(
      <AsManager>
        <AccessScreen />
      </AsManager>,
    )
    expect(await screen.findByText('Okres próbny: zostało 14 dni')).toBeInTheDocument()
    expect(screen.getByText('Ułożenia grafiku w tym miesiącu: 2 z 20.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Kod (12 znaków)'), { target: { value: 'ABCD-EFGH-JKMN' } })
    fireEvent.submit(screen.getByLabelText('Kod (12 znaków)').closest('form')!)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')).toMatchObject({
      url: '/api/companies/c1/subscription/redeem',
      body: { code: 'ABCD-EFGH-JKMN' },
    })
    expect(await screen.findByText('Kod przyjęty. Dostęp aktywny: zostało 44 dni.')).toBeInTheDocument()
  })

  it('has an error state', async () => {
    mockApi(() => [500, { detail: 'Błąd serwera.' }])
    renderScreen(
      <AsManager>
        <AccessScreen />
      </AsManager>,
    )
    expect(await screen.findByText('Błąd serwera.')).toBeInTheDocument()
  })
})
