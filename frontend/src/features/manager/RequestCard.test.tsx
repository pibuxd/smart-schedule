import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ManagerRequestOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { RequestCard } from './AvailabilityScreen'
import { AsManager } from './test-utils'

function request(changes: Partial<ManagerRequestOut> = {}): ManagerRequestOut {
  return {
    id: 'r1',
    employee_id: 'e1',
    employee_name: 'Julia Czarnecka',
    text: 'chce albo 12stego albo 13stego stycznia',
    status: 'needs_manager',
    summary: null,
    employee_corrected: false,
    unread_reason: 'off',
    can_reread: false,
    manager_priority: 'normal',
    manager_rejected: false,
    created_at: '2026-11-15T20:00:00Z',
    ...changes,
  }
}

const card = (r: ManagerRequestOut, periodId?: string) =>
  renderScreen(
    <AsManager>
      <ul>
        <RequestCard request={r} periodId={periodId} />
      </ul>
    </AsManager>,
  )

describe('RequestCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says the assistant is switched off instead of blaming it', async () => {
    mockApi(() => [200, {}])
    card(request())
    expect(await screen.findByText(/Asystent jest wyłączony/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Daj asystentowi do przeczytania' })).not.toBeInTheDocument()
  })

  it('hands a request that came while the assistant was off to it once it is on', async () => {
    const calls = mockApi(() => [200, request({ status: 'new', unread_reason: '' })])
    card(request({ can_reread: true }))
    expect(await screen.findByText(/przyszła, kiedy asystent był wyłączony/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Daj asystentowi do przeczytania' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')!.url).toContain('/api/requests/r1/reread')
  })

  it('shows the earlier message and the question an answer belongs to', async () => {
    mockApi(() => [200, {}])
    card(
      request({
        text: 'Od poniedziałku, przy piecu.',
        unread_reason: 'unsure',
        asked: { text: 'Po zabiegu nie mogę dźwigać blach.', question: 'Od kiedy i na których zmianach?' },
        exchange: [{ text: 'Po zabiegu nie mogę dźwigać blach.', question: 'Od kiedy i na których zmianach?' }],
      }),
    )
    expect(
      await screen.findByText(
        'Wcześniej: „Po zabiegu nie mogę dźwigać blach.” Asystent zapytał: „Od kiedy i na których zmianach?”',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('„Od poniedziałku, przy piecu.”')).toBeInTheDocument()
  })

  it('shows every question when the assistant asked several times', async () => {
    mockApi(() => [200, {}])
    card(
      request({
        text: 'Nie wiem.',
        unread_reason: 'unsure',
        asked: { text: 'Trochę mniej.', question: 'Ile najwyżej w tygodniu?' },
        exchange: [
          { text: 'Chcę mniej pracować.', question: 'Ile godzin?' },
          { text: 'Trochę mniej.', question: 'Ile najwyżej w tygodniu?' },
        ],
      }),
    )
    expect(await screen.findByText('Wcześniej: „Chcę mniej pracować.” Asystent zapytał: „Ile godzin?”')).toBeInTheDocument()
    expect(screen.getByText('Potem: „Trochę mniej.” Asystent zapytał: „Ile najwyżej w tygodniu?”')).toBeInTheDocument()
  })

  it('tells apart a request the assistant read but could not turn into a setting', async () => {
    mockApi(() => [200, {}])
    card(request({ unread_reason: 'unsure' }))
    expect(await screen.findByText(/Asystent przeczytał tę prośbę, ale nie umiał/)).toBeInTheDocument()
  })

  it('says when the employee forwarded a message the assistant refused', async () => {
    mockApi(() => [200, {}])
    card(request({ unread_reason: 'rejected', employee_corrected: true, can_reread: false }))
    expect(await screen.findByText(/Pracownik przekazał ją Tobie do oceny/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Daj asystentowi do przeczytania' })).not.toBeInTheDocument()
  })

  it('marks a lasting request and ends one from an earlier period from this one', async () => {
    const calls = mockApi(() => [200, {}])
    card(request({ lasting: true, carried_from: '2026-12-01', summary: 'Wolne w piątki.' }), 'p2')
    expect(await screen.findByText('Na stałe od grudnia')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Zakończ od tego okresu' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.url).toContain('/api/periods/p2/requests/r1/end')
    expect(post.body).toEqual({ ended: true })
  })

  it('cannot end a lasting request in the period it was written for', async () => {
    mockApi(() => [200, {}])
    card(request({ lasting: true, summary: 'Wolne w piątki.' }), 'p1')
    expect(await screen.findByText('Na stałe')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zakończ od tego okresu' })).not.toBeInTheDocument()
  })

  it('shows who ended a lasting request and lets the manager bring back their own ending', async () => {
    mockApi(() => [200, {}])
    const ended = { lasting: true, carried_from: '2026-12-01', ended: true }
    const first = card(request({ ...ended, ended_by: 'manager' }), 'p2')
    expect(await screen.findByText('Zakończona')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Przywróć prośbę' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Odrzuć prośbę' })).not.toBeInTheDocument()
    first.unmount()
    card(request({ ...ended, ended_by: 'employee' }), 'p2')
    expect(await screen.findByText(/Pracownik zakończył tę prośbę od tego okresu/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Przywróć prośbę' })).not.toBeInTheDocument()
  })
})
