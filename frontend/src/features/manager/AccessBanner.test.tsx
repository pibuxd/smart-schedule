import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSubscription } from '../../api/generated/billing/billing'
import { mockApi, renderScreen } from '../../test/render'
import { untilNextChange } from './access-refresh'
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

const DAY = 24 * 60 * 60 * 1000

describe('AccessBanner', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

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

  it('shows a code ending within a week', async () => {
    show({ ...trial, source: 'code', trial: false, days_left: 7, expiring_soon: true })
    expect(await screen.findByText('Dostęp aktywny: zostało 7 dni.')).toBeInTheDocument()
  })

  it('shows read-only mode after the trial', async () => {
    show({ ...trial, is_active: false, days_left: 0, read_only: true })
    expect(await screen.findByText('Okres próbny minął. Grafiki możesz oglądać, ale nie zmieniać.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Wpisz kod dostępu' })).toBeInTheDocument()
  })

  it('shows the strip in an open panel once the last 2 days start', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-12-24T10:00:00+01:00'))
    const endsAt = Date.parse('2026-12-26T10:00:10+01:00')
    // Answers like the server: whole days left, rounded up; the trial's strip from 2 days.
    const calls = mockApi(() => {
      const daysLeft = Math.ceil((endsAt - Date.now()) / DAY)
      return [200, { ...trial, ends_at: new Date(endsAt).toISOString(), days_left: daysLeft, expiring_soon: daysLeft <= 2 }]
    })
    renderScreen(<AccessBanner companyId="c1" />)
    await vi.waitFor(() => expect(calls).toHaveLength(1))
    await vi.advanceTimersByTimeAsync(1)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(2 * 60_000)

    expect(await screen.findByText('Okres próbny: zostały 2 dni.')).toBeInTheDocument()
    expect(calls).toHaveLength(2)
  })

  it('waits for the count of days to drop, and stops once read-only', () => {
    const now = Date.parse('2026-12-24T10:00:00Z')
    const endsAt = (ms: number) => new Date(now + ms).toISOString()
    expect(untilNextChange({ ...trial, ends_at: endsAt(2 * DAY + 3_600_000), days_left: 3 }, now)).toBe(3_601_000)
    expect(untilNextChange({ ...trial, ends_at: endsAt(10_000), days_left: 1 }, now)).toBe(60_000)
    expect(untilNextChange({ ...trial, ends_at: endsAt(-DAY), days_left: 0, read_only: true }, now)).toBe(false)
  })
})
