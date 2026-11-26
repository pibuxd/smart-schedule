import { fireEvent, screen, waitFor } from '@testing-library/react'
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

  it('opens "Kiedy mogę" on the month the manager asks about', async () => {
    const asked = {
      unread: 0,
      notifications: [
        {
          id: 'n3',
          kind: 'availability_requested',
          text: 'Kierownik prosi o dyspozycje na okres pt. 01.01 – niedz. 31.01 (Rynek).',
          link: 'availability',
          month: '2027-01',
          created_at: new Date(2026, 11, 1, 9, 30).toISOString(),
          read: true,
        },
      ],
    }
    mockApi(() => [200, asked])
    renderScreen(<NotificationsScreen companyId="c1" now={now} />)
    const link = await screen.findByRole('link', { name: 'Zaznacz, kiedy możesz' })
    expect(link.getAttribute('href')).toBe('/kiedy-moge?miesiac=2027-01')
  })

  it('removes one notification with the X and all with one button', async () => {
    const calls = mockApi((method) => (method === 'GET' ? [200, list] : [204, null]))
    renderScreen(<NotificationsScreen companyId="c1" now={now} />)
    await screen.findByText(/Ola Kos oddaje zmianę/)
    fireEvent.click(screen.getAllByRole('button', { name: 'Usuń powiadomienie' })[0])
    await waitFor(() => expect(screen.queryByText(/Ola Kos oddaje zmianę/)).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'DELETE')).toMatchObject({ url: '/api/me/notifications/n1' })
    expect(screen.getByText(/Jest nowy grafik/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Usuń wszystkie' }))
    expect(await screen.findByText('Nie masz powiadomień')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'DELETE').at(-1)).toMatchObject({
      url: '/api/me/notifications?company_id=c1',
    })
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
