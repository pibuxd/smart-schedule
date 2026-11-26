import { createFileRoute } from '@tanstack/react-router'

import { ScheduleScreen } from '../../../features/manager/ScheduleScreen'
import { searchId } from '../../../lib/focus'

export const Route = createFileRoute('/kierownik/lokal/$locationId/grafik')({
  // From a push notification: ?okres=<id> opens that period's schedule.
  validateSearch: (search: Record<string, unknown>): { okres?: string } => ({ okres: searchId(search.okres) }),
  component: Page,
})

function Page() {
  const { locationId } = Route.useParams()
  const { okres } = Route.useSearch()
  return <ScheduleScreen key={`${locationId}/${okres ?? ''}`} locationId={locationId} periodId={okres} />
}
