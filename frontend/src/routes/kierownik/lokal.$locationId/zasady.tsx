import { createFileRoute } from '@tanstack/react-router'

import { RulesScreen } from '../../../features/manager/RulesScreen'

export const Route = createFileRoute('/kierownik/lokal/$locationId/zasady')({
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  return <RulesScreen scope="location" scopeId={locationId} />
}
