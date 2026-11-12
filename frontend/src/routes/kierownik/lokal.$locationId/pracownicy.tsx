import { createFileRoute } from '@tanstack/react-router'

import { EmployeesScreen } from '../../../features/manager/EmployeesScreen'

export const Route = createFileRoute('/kierownik/lokal/$locationId/pracownicy')({
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  return <EmployeesScreen locationId={locationId} />
}
