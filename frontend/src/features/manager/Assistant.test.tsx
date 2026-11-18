import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { AssistantPanel } from './Assistant'
import { AsManager } from './test-utils'

const command = {
  id: 'cmd1',
  text: 'Ania i Kasia nie razem',
  status: 'ready',
  reply: 'Dodam polecenie, żeby Ania i Kasia nie pracowały razem.',
  question: null,
  lines: ['Nowe polecenie: Ania i Kasia: osobno, nie na tej samej zmianie.'],
  effects: [],
  notes: ['Polecenia mają kolejność: to wyżej wygrywa, gdy nie da się spełnić wszystkich.'],
  can_apply: true,
  created_at: '2026-11-13T10:00:00Z',
}

const instructions = (items: { id: string; text: string; active: boolean }[], enabled = true) => ({
  assistant_enabled: enabled,
  items,
})

const panel = () =>
  renderScreen(
    <AsManager>
      <AssistantPanel locationId="l1" />
    </AsManager>,
  )

describe('AssistantPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends a command, shows the plan in plain words and changes nothing until accepted', async () => {
    let applied = false
    const calls = mockApi((method, path) => {
      if (path === '/api/locations/l1/instructions') {
        return [200, instructions(applied ? [{ id: 'i1', text: 'Ania i Kasia: osobno', active: true }] : [])]
      }
      if (method === 'POST' && path === '/api/locations/l1/assistant-commands') {
        return [201, { ...command, status: 'queued', lines: [], notes: [], reply: null, can_apply: false }]
      }
      if (path === '/api/assistant-commands/cmd1/apply') {
        applied = true
        return [200, { ...command, status: 'applied', can_apply: false }]
      }
      if (path === '/api/assistant-commands/cmd1') return [200, applied ? { ...command, status: 'applied' } : command]
      return [404, { detail: 'nie ma' }]
    })
    panel()
    expect(await screen.findByText(/Nie ma jeszcze żadnych/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Twoje polecenie'), { target: { value: 'Ania i Kasia nie razem' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij asystentowi' }))

    expect(await screen.findByText(/Nowe polecenie: Ania i Kasia: osobno/)).toBeInTheDocument()
    expect(screen.getByText(/to wyżej wygrywa/)).toBeInTheDocument()
    expect(calls.some((c) => c.url.endsWith('/apply'))).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'Zatwierdź zmiany' }))
    expect(await screen.findByText(/Ustawienia zapisane/)).toBeInTheDocument()
    expect(await screen.findByText('Ania i Kasia: osobno')).toBeInTheDocument()
  })

  it('says so when the assistant is switched off', async () => {
    mockApi(() => [200, instructions([], false)])
    panel()
    expect(await screen.findByText(/Asystent jest wyłączony/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Twoje polecenie')).not.toBeInTheDocument()
  })

  it('shows a factual reply without suggesting another command or offering approval', async () => {
    mockApi((method, path) => {
      if (path.endsWith('/instructions')) return [200, instructions([])]
      return [method === 'POST' ? 201 : 200, {
        ...command, reply: 'Anna ma 120 godzin w opublikowanym grafiku.', lines: [], notes: [], can_apply: false,
      }]
    })
    panel()
    fireEvent.change(await screen.findByLabelText('Twoje polecenie'), { target: { value: 'Ile godzin ma Anna?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij asystentowi' }))
    expect(await screen.findByText('Anna ma 120 godzin w opublikowanym grafiku.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zatwierdź zmiany' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Napisz polecenie inaczej/)).not.toBeInTheDocument()
  })

  it('reorders and removes instructions', async () => {
    const items = [
      { id: 'i1', text: 'Ania i Kasia: osobno', active: true },
      { id: 'i2', text: 'Marek: tylko zmiana „Ranna”', active: true },
    ]
    const calls = mockApi((method) => (method === 'DELETE' ? [204, null] : [200, instructions(items)]))
    panel()
    fireEvent.click(await screen.findByRole('button', { name: 'Wyżej: Marek: tylko zmiana „Ranna”' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ ids: ['i2', 'i1'] })

    fireEvent.click(screen.getByRole('button', { name: 'Usuń: Ania i Kasia: osobno' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.method === 'DELETE')!.url).toBe('/api/instructions/i1')
  })
})
