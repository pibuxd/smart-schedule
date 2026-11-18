import { createFileRoute } from '@tanstack/react-router'

import { AssistantPanel } from '../../../features/manager/Assistant'

export const Route = createFileRoute('/kierownik/lokal/$locationId/asystent')({ component: Page })

function Page() {
  const { locationId } = Route.useParams()
  return <AssistantPanel key={locationId} locationId={locationId} />
}
