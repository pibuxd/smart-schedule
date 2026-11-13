import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { RulesScreen } from './RulesScreen'
import { AsManager } from './test-utils'

const item = (code: string, label: string, extra = {}) => ({
  code,
  label,
  description: '',
  good_practice: false,
  enabled: true,
  is_hard: false,
  params: {},
  param_names: [],
  source: 'group',
  group_value: { enabled: true, is_hard: false, params: {} },
  location_only: false,
  ...extra,
})

const rules = {
  scope: 'location',
  scope_id: 'l1',
  name: 'Wieliczka',
  group: { id: 'g1', name: 'Piekarnie' },
  positions: [],
  shift_types: [],
  items: [
    item('min_rest_between_shifts', 'Odpoczynek między zmianami', { param_names: ['hours'], params: { hours: 11 } }),
    item('target_hours', 'Cel godzin'),
    item('max_shifts_per_week', 'Zmiany w tygodniu', { enabled: false, source: 'off', group_value: null }),
  ],
}

describe('RulesScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reorders, shows the effect on the last schedule, then saves the whole list', async () => {
    const preview = {
      lines: ['„Cel godzin”: w grafiku 01.12–31.12.2026 byłaby złamana 4 razy.'],
      period: '01.12–31.12.2026',
      manager_rules_before: 91,
      manager_rules_after: 89,
    }
    const calls = mockApi((_method, path) => {
      if (path.endsWith('/preview')) return [200, preview]
      if (path.endsWith('/instructions')) return [200, { assistant_enabled: true, items: [] }]
      return [200, rules]
    })
    renderScreen(
      <AsManager>
        <RulesScreen scope="location" scopeId="l1" />
      </AsManager>,
    )
    const save = await screen.findByRole('button', { name: 'Sprawdź skutek i zapisz' })
    expect(save).toBeDisabled()
    expect(screen.getAllByText('z grupy')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'Wyżej: Cel godzin' }))
    fireEvent.click(save)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/byłaby złamana 4 razy/)).toBeInTheDocument()
    expect(within(dialog).getByText('91 %')).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Zapisz zasady' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.url).toBe('/api/scopes/location/l1/rules')
    expect((put.body as { items: { code: string }[] }).items.map((i) => i.code)).toEqual([
      'target_hours',
      'min_rest_between_shifts',
      'max_shifts_per_week',
    ])
  })

  it('"bez wyjątków" needs the rule switched on', async () => {
    mockApi((_method, path) =>
      path.endsWith('/instructions') ? [200, { assistant_enabled: false, items: [] }] : [200, rules],
    )
    renderScreen(
      <AsManager>
        <RulesScreen scope="location" scopeId="l1" />
      </AsManager>,
    )
    await screen.findByText('Zmiany w tygodniu')
    const hard = screen.getAllByRole('checkbox', { name: /Bez wyjątków/ })
    expect(hard[2]).toBeDisabled()
    expect(hard[0]).toBeEnabled()
  })
})
