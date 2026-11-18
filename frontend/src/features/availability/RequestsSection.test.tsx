import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { RequestsSection } from './RequestsSection'

const request = (over = {}) => ({
  id: 'r1',
  text: 'Wolałabym nie pracować w piątki.',
  status: 'interpreted',
  summary: 'Wolne w piątki, jeśli się da.',
  created_at: '2026-11-01T10:00:00Z',
  ...over,
})

describe('RequestsSection', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows how the request was understood and lets the person say it is wrong', async () => {
    let rows = [request()]
    const calls = mockApi((method) => {
      if (method === 'PATCH') {
        rows = [request({ status: 'needs_manager', summary: null })]
        return [200, rows[0]]
      }
      return [200, rows]
    })
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />)
    expect(await screen.findByText('Wolne w piątki, jeśli się da.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Nie o to mi chodziło' }))
    expect(await screen.findByText('Kierownik przeczyta tę prośbę sam.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ understood: false })
  })

  it('a request nobody interpreted simply goes to the manager', async () => {
    mockApi(() => [200, [request({ status: 'needs_manager', summary: null })]])
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable={false} />)
    expect(await screen.findByText('Kierownik przeczyta tę prośbę sam.')).toBeInTheDocument()
    expect(screen.queryByText(/Tak to zrozumieliśmy/)).not.toBeInTheDocument()
  })

  it('says that the assistant also reads the request, only when it does', async () => {
    mockApi(() => [200, []])
    const { unmount } = renderScreen(<RequestsSection companyId="c1" periodId="p1" editable assistantReads />)
    expect(await screen.findByText(/Twoje wcześniejsze prośby, dyspozycje i opublikowany grafik/)).toBeInTheDocument()
    expect(screen.queryByText(/Przeczyta to tylko kierownik/)).not.toBeInTheDocument()
    unmount()

    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />)
    expect(await screen.findByText(/Przeczyta to tylko kierownik/)).toBeInTheDocument()
  })

  it('keeps superseded requests visible without an edit action', async () => {
    mockApi(() => [200, [request({ status: 'superseded', summary: null })]])
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />)
    expect(await screen.findByText(/Ta prośba została zastąpiona/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edytuj prośbę' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nie o to mi chodziło' })).not.toBeInTheDocument()
  })

  it('shows an informational answer without claiming it was sent to the manager', async () => {
    mockApi(() => [200, [request({ status: 'answered', summary: 'W publikacji masz 120 godzin.' })]])
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />)
    expect(await screen.findByText('W publikacji masz 120 godzin.')).toBeInTheDocument()
    expect(screen.queryByText('Wysłane do kierownika')).not.toBeInTheDocument()
  })
})
