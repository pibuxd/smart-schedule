import type { ManagerHoursChangesOut } from '../../api/generated/model'
import { useManagerHoursChanges } from '../../api/generated/worktime/worktime'

/** How often the list and the header badge look for new reports of other hours. */
export const HOURS_REFRESH_MS = 60_000

/** Reports of other hours waiting for the manager's decision, for the badge in the header. */
export function useWaitingHours(companyId: string): number {
  const query = useManagerHoursChanges({ company_id: companyId }, { query: { refetchInterval: HOURS_REFRESH_MS } })
  return query.data?.status === 200 ? (query.data.data as ManagerHoursChangesOut).waiting : 0
}
