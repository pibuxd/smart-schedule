import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { HandoverRule, RulesScreen } from './RulesScreen'
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
  group_value: { enabled: true, is_hard: false, position: code === 'target_hours' ? 2 : 1, params: code === 'min_rest_between_shifts' ? { hours: 11 } : {} },
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
    const save = await screen.findByRole('button', { name: 'Sprawdź i zapisz' })
    expect(save).toBeDisabled()
    expect(screen.getAllByText('z grupy')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'Wyżej: Cel godzin' }))
    const movedCard = screen.getByText('Cel godzin', { selector: 'b' }).closest('li')!
    expect(within(movedCard).getByText('zmienione w tym lokalu')).toBeInTheDocument()
    fireEvent.click(within(movedCard).getByRole('button', { name: 'Przywróć jak w grupie' }))
    expect(save).toBeDisabled()
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

  it('switches handing over given-away shifts without approval and saves it at once', async () => {
    let location = { id: 'l1', name: 'Wieliczka', handover_without_approval: false }
    const waitingOffer = { id: 'o1', status: 'claimed', shift: { location_id: 'l1' }, claims: [] }
    const calls = mockApi((method, path, body) => {
      if (method === 'PATCH') {
        location = { ...location, ...(body as object) }
        return [200, location]
      }
      if (path === '/api/manager/offers') return [200, { offers: [waitingOffer], waiting: 1 }]
      return [200, location]
    })
    renderScreen(
      <AsManager>
        <HandoverRule locationId="l1" />
      </AsManager>,
    )
    const box = await screen.findByRole('checkbox', { name: /Przejęcie oddanej zmiany bez zatwierdzania/ })
    expect(box).not.toBeChecked()
    fireEvent.click(box)
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.url).toBe('/api/locations/l1')
    expect(patch.body).toEqual({ handover_without_approval: true })
    expect(await screen.findByText('Zapisane.')).toBeInTheDocument()
    // Someone volunteered before the switch: the manager still has to decide that one.
    expect(await screen.findByText(/Jedna oddana zmiana z tego lokalu nadal czeka/)).toBeInTheDocument()
  })
})
