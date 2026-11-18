import { createFileRoute } from '@tanstack/react-router'

import { AssistantPanel } from '../../../features/manager/Assistant'

export const Route = createFileRoute('/kierownik/lokal/$locationId/asystent')({
  validateSearch: (search: Record<string, unknown>): { periodId?: string } => ({
    periodId: typeof search.periodId === 'string' ? search.periodId : undefined,
  }),
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  const { periodId } = Route.useSearch()
  return <AssistantPanel key={`${locationId}:${periodId}`} locationId={locationId} periodId={periodId} />
}
