import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSubscription } from '../../api/generated/billing/billing'
import { mockApi, renderScreen } from '../../test/render'
import { AccessBanner } from './AccessBanner'

const trial = {
  is_active: true,
  source: 'trial',
  trial: true,
  ends_at: '2026-12-26T10:00:00+01:00',
  days_left: 30,
  read_only: false,
  expiring_soon: false,
}

/** Shares the banner's query, so once it says "Wczytane" the banner has the answer too. */
function Loaded() {
  return useSubscription('c1').isSuccess ? <p>Wczytane</p> : null
}

function show(subscription: object) {
  mockApi(() => [200, subscription])
  renderScreen(
    <>
      <Loaded />
      <AccessBanner companyId="c1" />
    </>,
  )
}

describe('AccessBanner', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('stays hidden during the trial until the last 2 days', async () => {
    show(trial)
    expect(await screen.findByText('Wczytane')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByText(/Okres próbny/)).not.toBeInTheDocument()
  })

  it('shows the trial when 2 days are left', async () => {
    show({ ...trial, days_left: 2, expiring_soon: true })
    expect(await screen.findByText('Okres próbny: zostały 2 dni.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dostęp i kod' })).toBeInTheDocument()
  })

  it('stays hidden for a code with many days left', async () => {
    show({ ...trial, source: 'code', trial: false, days_left: 20 })
    expect(await screen.findByText('Wczytane')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows read-only mode after the trial', async () => {
    show({ ...trial, is_active: false, days_left: 0, read_only: true })
    expect(await screen.findByText('Okres próbny minął. Grafiki możesz oglądać, ale nie zmieniać.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Wpisz kod dostępu' })).toBeInTheDocument()
  })
})
