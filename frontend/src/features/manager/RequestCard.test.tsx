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

const card = (r: ManagerRequestOut) =>
  renderScreen(
    <AsManager>
      <ul>
        <RequestCard request={r} />
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
})
