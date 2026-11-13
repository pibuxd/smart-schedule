import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect } from 'react'

import type { NotificationOut, NotificationsOut } from '../../api/generated/model'
import {
  getMyNotificationsQueryKey,
  useMarkNotificationsRead,
  useMyNotifications,
} from '../../api/generated/notifications/notifications'
import { EmptyState, ErrorState, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import { NOTIFICATIONS_REFRESH_MS, whenText } from './unread'

const LINKS = {
  schedule: { to: '/grafik', label: 'Zobacz „Mój grafik”' },
  availability: { to: '/kiedy-moge', label: 'Zaznacz, kiedy możesz' },
  offers: { to: '/kierownik/oddane-zmiany', label: 'Otwórz „Oddane zmiany”' },
} as const

/** In-app notifications, newest first. Opening the screen marks them as seen; new ones stay highlighted once. */
export function NotificationsScreen({ companyId, now = new Date() }: { companyId: string; now?: Date }) {
  const notifications = useMyNotifications({ company_id: companyId }, { query: { refetchInterval: NOTIFICATIONS_REFRESH_MS } })
  const markRead = useMarkNotificationsRead()
  const queryClient = useQueryClient()
  const data = notifications.data?.status === 200 ? (notifications.data.data as NotificationsOut) : undefined
  const unseen = data?.notifications.filter((n) => !n.read).map((n) => n.id) ?? []
  const unseenKey = unseen.join(',')

  useEffect(() => {
    if (!unseenKey) return
    const key = getMyNotificationsQueryKey({ company_id: companyId })
    markRead.mutate(
      { data: { company_id: companyId, ids: unseenKey.split(',') } },
      {
        // The badge drops to zero now; the list keeps "Nowe" on what was new until the next refresh.
        onSuccess: () =>
          queryClient.setQueryData(key, (old: typeof notifications.data) =>
            old?.status === 200 ? { ...old, data: { ...old.data, unread: 0 } } : old,
          ),
      },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per set of unseen notifications
  }, [companyId, unseenKey])

  if (notifications.isPending) return <Loading>Wczytuję powiadomienia…</Loading>
  if (notifications.isError || !data) {
    return (
      <ErrorState onRetry={() => void notifications.refetch()}>
        {errorMessage(notifications.error, 'Nie udało się wczytać powiadomień. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  if (data.notifications.length === 0) {
    return (
      <EmptyState title="Nie masz powiadomień">
        <p className="m-0">
          Tu zobaczysz, gdy kierownik poprosi o dyspozycje, opublikuje grafik albo ktoś odda zmianę, którą możesz wziąć.
        </p>
      </EmptyState>
    )
  }
  return (
    <ul className="m-0 grid list-none gap-3 p-0">
      {data.notifications.map((notification) => (
        <NotificationItem key={notification.id} notification={notification} now={now} />
      ))}
    </ul>
  )
}

function NotificationItem({ notification, now }: { notification: NotificationOut; now: Date }) {
  const link = notification.link === 'none' ? null : LINKS[notification.link]
  return (
    <li
      className={
        'grid gap-2 rounded-lg border bg-surface p-4 ' +
        (notification.read ? 'border-line' : 'border-l-8 border-accent')
      }
    >
      <div className="flex items-baseline justify-between gap-3 text-sm text-ink-muted">
        <span>{whenText(new Date(notification.created_at), now)}</span>
        {!notification.read && <b className="text-accent">Nowe</b>}
      </div>
      <p className="m-0 text-base">{notification.text}</p>
      {link && (
        <Link to={link.to} className="min-h-(--touch) content-center font-semibold text-accent underline underline-offset-4">
          {link.label}
        </Link>
      )}
    </li>
  )
}
