import { useManagerOffers } from '../../api/generated/marketplace/marketplace'
import type { ManagerOffersOut } from '../../api/generated/model'

/** How often the list and the header badge look for new volunteers. */
export const OFFERS_REFRESH_MS = 60_000

/** Volunteers waiting for the manager's decision, for the badge in the header. */
export function useWaitingClaims(companyId: string): number {
  const query = useManagerOffers({ company_id: companyId }, { query: { refetchInterval: OFFERS_REFRESH_MS } })
  return query.data?.status === 200 ? (query.data.data as ManagerOffersOut).waiting : 0
}
