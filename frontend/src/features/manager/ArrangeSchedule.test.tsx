import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { RunProgress } from './ArrangeSchedule'
import { AsManager } from './test-utils'

const run = {
  id: 'r1',
  status: 'running',
  solver_status: '',
  period_ids: ['p1'],
  created_at: '2026-11-13T10:00:00+01:00',
  started_at: '2026-11-13T10:00:01+01:00',
  finished_at: null,
  time_ms: null,
  error: '',
  versions: [],
}

describe('RunProgress', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lets the manager cancel a schedule that is being arranged', async () => {
    let status = 'running'
    const calls = mockApi((method) => {
      if (method === 'POST') status = 'cancelled'
      return [200, { ...run, status }]
    })
    renderScreen(
      <AsManager>
        <RunProgress runId="r1" />
      </AsManager>,
    )
    expect(await screen.findByText('Układam grafik…')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Anuluj' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/api/generation-runs/r1/cancel'))).toBe(true),
    )
    expect(await screen.findByText('Układanie anulowane. Nic się nie zmieniło.')).toBeInTheDocument()
  })

  it('has no cancel button when the company is read-only', async () => {
    mockApi(() => [200, run])
    renderScreen(
      <AsManager readOnly>
        <RunProgress runId="r1" />
      </AsManager>,
    )
    expect(await screen.findByText('Układam grafik…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Anuluj' })).not.toBeInTheDocument()
  })
})
