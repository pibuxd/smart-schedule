import { createFileRoute } from '@tanstack/react-router'

import { useEmployee } from '../../features/auth/EmployeeContext'
import { NotificationsScreen } from '../../features/notifications/NotificationsScreen'

export const Route = createFileRoute('/_pracownik/powiadomienia')({
  component: NotificationsPage,
})

function NotificationsPage() {
  const { companyId } = useEmployee()
  return (
    <div className="grid gap-4">
      <h1 className="m-0 text-xl font-extrabold">Powiadomienia</h1>
      <NotificationsScreen companyId={companyId} />
    </div>
  )
}
