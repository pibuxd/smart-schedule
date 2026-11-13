import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { NotificationsScreen } from './NotificationsScreen'
import { whenText } from './unread'

const now = new Date(2026, 11, 3, 15, 0)

const list = {
  unread: 1,
  notifications: [
    {
      id: 'n1',
      kind: 'shift_offered',
      text: 'Ola Kos oddaje zmianę: pt. 04.12, 06:00–14:00, Sprzedawca, Rynek.',
      link: 'schedule',
      created_at: new Date(2026, 11, 3, 14, 5).toISOString(),
      read: false,
    },
    {
      id: 'n2',
      kind: 'schedule_published',
      text: 'Jest nowy grafik na okres pon. 07.12 – niedz. 13.12 (Rynek). Sprawdź swoje zmiany.',
      link: 'schedule',
      created_at: new Date(2026, 11, 1, 9, 30).toISOString(),
      read: true,
    },
  ],
}

describe('NotificationsScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists notifications, highlights new ones and marks them as seen', async () => {
    const calls = mockApi((method) => (method === 'POST' ? [204, null] : [200, list]))
    renderScreen(<NotificationsScreen companyId="c1" now={now} />)
    expect(await screen.findByText(/Ola Kos oddaje zmianę/)).toBeInTheDocument()
    expect(screen.getByText('Nowe')).toBeInTheDocument()
    expect(screen.getByText('dzisiaj, 14:05')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Zobacz „Mój grafik”' })).toHaveLength(2)
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')).toMatchObject({
        url: '/api/me/notifications/read',
        body: { company_id: 'c1', ids: ['n1'] },
      }),
    )
  })

  it('explains what will appear when there is nothing', async () => {
    mockApi(() => [200, { unread: 0, notifications: [] }])
    renderScreen(<NotificationsScreen companyId="c1" />)
    expect(await screen.findByText('Nie masz powiadomień')).toBeInTheDocument()
  })

  it('shows a plain error with a retry button', async () => {
    mockApi(() => [500, {}])
    renderScreen(<NotificationsScreen companyId="c1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać powiadomień')
  })

  it('says when in plain words', () => {
    expect(whenText(new Date(2026, 11, 2, 9, 30), now)).toBe('wczoraj, 9:30')
    expect(whenText(new Date(2026, 10, 28, 18, 0), now)).toBe('28.11, 18:00')
  })
})
