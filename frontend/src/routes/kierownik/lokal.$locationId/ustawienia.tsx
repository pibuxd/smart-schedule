import { createFileRoute } from '@tanstack/react-router'

import { LocationSettingsScreen } from '../../../features/manager/SettingsScreen'

export const Route = createFileRoute('/kierownik/lokal/$locationId/ustawienia')({
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  return <LocationSettingsScreen locationId={locationId} />
}
