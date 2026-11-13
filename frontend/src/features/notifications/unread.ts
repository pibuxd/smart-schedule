import type { NotificationsOut } from '../../api/generated/model'
import { useMyNotifications } from '../../api/generated/notifications/notifications'

/** How often the badge and the list look for new notifications (no push, no websockets). */
export const NOTIFICATIONS_REFRESH_MS = 60_000

/** The number of unseen notifications, for the badge on the tab. */
export function useUnreadNotifications(companyId: string): number {
  const query = useMyNotifications({ company_id: companyId }, { query: { refetchInterval: NOTIFICATIONS_REFRESH_MS } })
  return query.data?.status === 200 ? (query.data.data as NotificationsOut).unread : 0
}

/** "dzisiaj, 14:05", "wczoraj, 9:30", "3.12, 18:00" */
export function whenText(at: Date, now: Date): string {
  const time = `${at.getHours()}:${String(at.getMinutes()).padStart(2, '0')}`
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((day(now) - day(at)) / 86_400_000)
  if (days === 0) return `dzisiaj, ${time}`
  if (days === 1) return `wczoraj, ${time}`
  return `${at.getDate()}.${String(at.getMonth() + 1).padStart(2, '0')}, ${time}`
}
