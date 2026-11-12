import { createFileRoute } from '@tanstack/react-router'

import { LocationLayout } from '../../features/manager/LocationLayout'

export const Route = createFileRoute('/kierownik/lokal/$locationId')({
  component: LocationPage,
})

function LocationPage() {
  const { locationId } = Route.useParams()
  return <LocationLayout locationId={locationId} />
}
