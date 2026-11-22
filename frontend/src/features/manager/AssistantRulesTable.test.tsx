import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { InstructionsOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { AssistantDrawerProvider } from './AssistantDrawer'
import { AssistantRulesTable } from './AssistantRulesTable'
import { AsManager } from './test-utils'

const agreements = (over: Partial<InstructionsOut> = {}): InstructionsOut => ({
  assistant_enabled: true,
  items: [
    { id: 'i1', text: 'Ania i Kasia: osobno', active: true },
    { id: 'i2', text: 'Marek: rano', active: true },
  ],
  rule_set_id: 'set1',
  period_id: 'p1',
  period_label: '01.12.2026–31.12.2026',
  period_requested: true,
  consumed_at: null,
  closed: false,
  rules: [
    {
      code: 'max_shifts_per_week',
      label: 'Zmiany w tygodniu',
      enabled: true,
      is_hard: false,
      details: 'Najwięcej zmian: 4',
      changed: true,
    },
    {
      code: 'min_rest',
      label: 'Odpoczynek między zmianami',
      enabled: true,
      is_hard: true,
      details: '',
      changed: false,
    },
  ],
  ...over,
})

const show = (readOnly = false) =>
  renderScreen(
    <AsManager readOnly={readOnly}>
      <AssistantDrawerProvider>
        <AssistantRulesTable locationId="l1" />
      </AssistantDrawerProvider>
    </AsManager>,
  )

describe('AssistantRulesTable', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reorders and removes approved instructions', async () => {
    const calls = mockApi((method) => (method === 'DELETE' ? [204, null] : [200, agreements()]))
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Wyżej: Marek: rano' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ ids: ['i2', 'i1'] })
    fireEvent.click(screen.getByRole('button', { name: 'Usuń: Ania i Kasia: osobno' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Tak, usuń' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/instructions/i1' && c.method === 'DELETE')).toBe(true))
  })

  it('puts a rule agreed in the chat back to the location setting', async () => {
    const calls = mockApi(() => [200, agreements()])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Przywróć obecne ustawienie lokalu: Zmiany w tygodniu' }))
    fireEvent.click(screen.getByRole('button', { name: 'Nie' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Przywróć obecne ustawienie lokalu: Zmiany w tygodniu' }))
    fireEvent.click(screen.getByRole('button', { name: 'Tak, przywróć' }))
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'DELETE' && c.url === '/api/locations/l1/agreed-rules/max_shifts_per_week'),
      ).toBe(true),
    )
    // Rules that were not agreed in the chat have no actions.
    expect(screen.queryByRole('button', { name: /Odpoczynek między zmianami/ })).not.toBeInTheDocument()
  })

  it('slides the chat in with a draft that is not sent by itself', async () => {
    const calls = mockApi((_method, path) => (path.endsWith('/assistant-commands') ? [200, []] : [200, agreements()]))
    show()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Zmień: Marek: rano' }))
    const chat = await screen.findByRole('dialog', { name: 'Asystent' })
    expect(await within(chat).findByLabelText('Twoja wiadomość')).toHaveValue('Zmień polecenie „Marek: rano”: ')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    fireEvent.click(within(chat).getByRole('button', { name: /Zamknij/ }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('is read-only after the schedule of the period is published', async () => {
    mockApi(() => [200, agreements({ closed: true, consumed_at: '2026-11-30T10:00:00Z' })])
    show()
    expect(await screen.findByText(/wykorzystane w opublikowanym grafiku/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Usuń|Zmień|Przywróć|Wyżej|Ustal w rozmowie/ })).not.toBeInTheDocument()
  })

  it('says what will appear here when nothing is agreed yet', async () => {
    mockApi(() => [200, agreements({ items: [], rules: [] })])
    show()
    expect(await screen.findByText(/Nic jeszcze nie ustalono/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ustal w rozmowie' })).toBeInTheDocument()
  })
})
