import { createFileRoute } from '@tanstack/react-router'

import { ScheduleScreen } from '../../../features/manager/ScheduleScreen'

export const Route = createFileRoute('/kierownik/lokal/$locationId/grafik')({
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  return <ScheduleScreen locationId={locationId} />
}
