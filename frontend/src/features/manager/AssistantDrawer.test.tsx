import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { InstructionsOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { useChatLocation } from './assistant-drawer'
import { AssistantDrawerProvider } from './AssistantDrawer'
import { AsManager } from './test-utils'

const instructions: InstructionsOut = {
  assistant_enabled: true,
  items: [],
  rule_set_id: 'set1',
  period_id: 'p1',
  period_label: 'Grudzień 2026',
  period_requested: true,
  consumed_at: null,
  closed: false,
  rules: [],
}

const place = (id: string, name: string) => ({ id, name, group_name: null })

function api(locations = [place('l1', 'Rynek')]) {
  return mockApi((_method, path) => {
    if (path === '/api/manager/overview') return [200, { locations, archived: [], groups: [] }]
    if (path.endsWith('/instructions')) return [200, instructions]
    return [200, []]
  })
}

/** A location's screen, which tells the chat it is open. */
function LocationScreen({ id }: { id: string }) {
  useChatLocation(id)
  return <p>Grafik lokalu</p>
}

const show = (screenUi = <p>Pracownicy firmy</p>, readOnly = false) =>
  renderScreen(
    <AsManager readOnly={readOnly}>
      <AssistantDrawerProvider>{screenUi}</AssistantDrawerProvider>
    </AsManager>,
  )

const historyOf = (calls: { url: string }[], id: string) =>
  calls.some((c) => c.url === `/api/locations/${id}/assistant-commands`)

describe('Assistant button on every manager screen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opens the chat of the only location from a screen outside any location', async () => {
    const calls = api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Asystent' }))
    const chat = await screen.findByRole('dialog', { name: 'Asystent' })
    expect(await within(chat).findByLabelText('Twoja wiadomość')).toBeInTheDocument()
    expect(historyOf(calls, 'l1')).toBe(true)
    expect(within(chat).queryByText(/Lokal:/)).not.toBeInTheDocument()
    // The open chat covers the corner, so the button steps aside.
    expect(screen.queryByRole('button', { name: 'Asystent' })).not.toBeInTheDocument()
  })

  it('asks which location first when there are several, and lets the manager switch', async () => {
    const calls = api([place('l1', 'Rynek'), place('l2', 'Dworzec')])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Asystent' }))
    const chat = await screen.findByRole('dialog', { name: 'Asystent' })
    expect(await within(chat).findByText('O którym lokalu rozmawiamy?')).toBeInTheDocument()
    expect(historyOf(calls, 'l1') || historyOf(calls, 'l2')).toBe(false)

    fireEvent.click(within(chat).getByRole('button', { name: 'Dworzec' }))
    expect(await within(chat).findByText('Dworzec')).toBeInTheDocument()
    await waitFor(() => expect(historyOf(calls, 'l2')).toBe(true))
    fireEvent.click(within(chat).getByRole('button', { name: 'Zmień lokal' }))
    expect(within(chat).getByRole('button', { name: 'Rynek' })).toBeInTheDocument()
  })

  it('talks about the location on screen without asking', async () => {
    const calls = api([place('l1', 'Rynek'), place('l2', 'Dworzec')])
    show(<LocationScreen id="l2" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Asystent' }))
    const chat = await screen.findByRole('dialog', { name: 'Asystent' })
    expect(await within(chat).findByLabelText('Twoja wiadomość')).toBeInTheDocument()
    expect(historyOf(calls, 'l2')).toBe(true)
    expect(within(chat).queryByText('O którym lokalu rozmawiamy?')).not.toBeInTheDocument()
    // With several locations the chat names its own, also when it covers the page on a phone.
    expect(await within(chat).findByText('Dworzec')).toBeInTheDocument()
    expect(within(chat).queryByRole('button', { name: 'Zmień lokal' })).not.toBeInTheDocument()
  })

  it('has no button while the company has no access', async () => {
    api()
    show(<p>Pracownicy firmy</p>, true)
    expect(await screen.findByText('Pracownicy firmy')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Asystent' })).not.toBeInTheDocument()
  })
})
