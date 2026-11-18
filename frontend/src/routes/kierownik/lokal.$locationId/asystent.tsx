import { createFileRoute } from '@tanstack/react-router'

import { AssistantRulesTable } from '../../../features/manager/AssistantRulesTable'

export const Route = createFileRoute('/kierownik/lokal/$locationId/asystent')({
  validateSearch: (search: Record<string, unknown>): { periodId?: string } => ({
    periodId: typeof search.periodId === 'string' ? search.periodId : undefined,
  }),
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  const { periodId } = Route.useSearch()
  return <AssistantRulesTable key={`${locationId}:${periodId}`} locationId={locationId} periodId={periodId} />
}
