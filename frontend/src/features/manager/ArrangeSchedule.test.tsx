import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ExperiencedShortOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { ArrangeButton, RunProgress } from './ArrangeSchedule'
import { AsManager } from './test-utils'

const run = {
  id: 'r1',
  status: 'running',
  different: false,
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
    expect(await screen.findByText('Anulowane. Nic się nie zmieniło.')).toBeInTheDocument()
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

describe('ArrangeButton', () => {
  afterEach(() => vi.unstubAllGlobals())

  const target = {
    periodId: 'p1',
    locationId: 'l1',
    locationName: 'ten lokal',
    missing: 0,
    deadlinePassed: true,
    manualChanges: 0,
    hasVersion: false,
    experiencedShort: [] as ExperiencedShortOut[],
  }

  it('warns before arranging when the location has too few experienced people, and still arranges', async () => {
    const calls = mockApi(() => [200, [run]])
    const short = [
      { position_id: 'k', position_name: 'Kelner', needed: 2, available: 1, day: '2026-11-27', shift_name: 'Zamknięcie' },
      { position_id: 'b', position_name: 'Barista', needed: 1, available: 0, day: '2026-11-23', shift_name: 'Rano' },
    ]
    renderScreen(
      <AsManager>
        <ArrangeButton targets={[{ ...target, experiencedShort: short }]} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ułóż grafik' }))
    const sheet = await screen.findByRole('dialog')
    expect(sheet).toHaveTextContent('Masz za mało doświadczonych osób.')
    expect(sheet).toHaveTextContent('Kelner: zmiana Zamknięcie (pt 27 listopada) potrzebuje 2, a w tym lokalu masz 1.')
    expect(sheet).toHaveTextContent('Barista: zmiana Rano (pon 23 listopada) potrzebuje 1, a w tym lokalu nie masz żadnej.')

    fireEvent.click(within(sheet).getByRole('button', { name: 'Ułóż grafik' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/api/periods/generate'))).toBe(true))
  })

  it('arranges a clearly different schedule when asked to', async () => {
    const calls = mockApi(() => [200, [run]])
    renderScreen(
      <AsManager>
        <ArrangeButton targets={[{ ...target, hasVersion: true, manualChanges: 2 }]} different />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ułóż inaczej' }))
    const sheet = await screen.findByRole('dialog')
    expect(sheet).toHaveTextContent('Ułożyć inny grafik?')
    expect(sheet).toHaveTextContent('Co trzecia zmiana dostanie inną osobę niż w ostatnich wersjach')
    expect(sheet).toHaveTextContent('Stracisz ręczne poprawki bez przypięcia: 2.')
    expect(sheet).toHaveTextContent('Gdy nowy będzie gorszy, usuń go koszem, a wróci obecny.')

    fireEvent.click(within(sheet).getByRole('button', { name: 'Ułóż inny grafik' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/periods/generate'))
      expect(post?.body).toEqual({ period_ids: ['p1'], different: true })
    })
  })

  it('arranges again without asking for a different schedule', async () => {
    const calls = mockApi(() => [200, [run]])
    renderScreen(
      <AsManager>
        <ArrangeButton targets={[{ ...target, hasVersion: true }]} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ułóż od nowa' }))
    const sheet = await screen.findByRole('dialog')
    expect(sheet).not.toHaveTextContent('inną osobę')
    fireEvent.click(within(sheet).getByRole('button', { name: 'Ułóż grafik' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/periods/generate'))
      expect(post?.body).toEqual({ period_ids: ['p1'] })
    })
  })

  it('says nothing about experience when there is enough of it', async () => {
    mockApi(() => [200, [run]])
    renderScreen(
      <AsManager>
        <ArrangeButton targets={[target]} />
      </AsManager>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ułóż grafik' }))
    expect(await screen.findByRole('dialog')).not.toHaveTextContent('doświadczonych')
  })
})
