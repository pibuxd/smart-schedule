import { createFileRoute } from '@tanstack/react-router'

import { useManager } from '../../features/manager/ManagerContext'
import { NotificationsScreen } from '../../features/notifications/NotificationsScreen'
import { PhonePushSwitch } from '../../features/notifications/PhonePushSwitch'

export const Route = createFileRoute('/kierownik/powiadomienia')({
  component: ManagerNotificationsPage,
})

/** The manager reads notifications without leaving the manager's panel. */
function ManagerNotificationsPage() {
  const { companyId } = useManager()
  return (
    <div className="mx-auto grid w-full max-w-(--column) gap-4">
      <h1 className="m-0 text-xl font-extrabold">Powiadomienia</h1>
      <PhonePushSwitch />
      <NotificationsScreen companyId={companyId} forManager />
    </div>
  )
}
