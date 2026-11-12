import { createFileRoute } from '@tanstack/react-router'

import { AvailabilityOverviewScreen } from '../../../features/manager/AvailabilityScreen'

export const Route = createFileRoute('/kierownik/lokal/$locationId/dyspozycje')({
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  return <AvailabilityOverviewScreen locationId={locationId} />
}
