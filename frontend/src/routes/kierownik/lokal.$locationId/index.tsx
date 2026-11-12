import { createFileRoute, Navigate } from '@tanstack/react-router'

export const Route = createFileRoute('/kierownik/lokal/$locationId/')({
  component: LocationStart,
})

function LocationStart() {
  const { locationId } = Route.useParams()
  return <Navigate to="/kierownik/lokal/$locationId/dyspozycje" params={{ locationId }} replace />
}
