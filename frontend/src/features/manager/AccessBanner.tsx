import { Link } from '@tanstack/react-router'

import { useSubscription } from '../../api/generated/billing/billing'
import type { SubscriptionOut } from '../../api/generated/model'
import { untilNextChange } from './access-refresh'
import { statusWords } from './words'

/**
 * A strip at the top of the manager's panel, only for read-only mode or access ending soon (`expiring_soon`:
 * 7 days before a code ends, 2 before the trial does). Until then the state is only on "Dostęp" (Piotr, 26.11.2026).
 */
export function AccessBanner({ companyId }: { companyId: string }) {
  const subscription = useSubscription(companyId, {
    query: {
      staleTime: 60_000,
      // An open panel asks again when the count of days drops, so the strip appears without a reload.
      refetchInterval: (query) => (query.state.data?.status === 200 ? untilNextChange(query.state.data.data) : false),
      refetchIntervalInBackground: true,
    },
  })
  if (!subscription.isSuccess) return null
  const data = subscription.data.data as SubscriptionOut
  if (!data.read_only && !data.expiring_soon) return null
  const tone = data.read_only ? 'border-cannot bg-cannot-soft text-cannot' : 'border-accent bg-accent-soft text-ink'
  const words = data.read_only
    ? data.trial
      ? 'Okres próbny minął. Grafiki możesz oglądać, ale nie zmieniać.'
      : 'Grafiki możesz teraz tylko oglądać.'
    : `${statusWords(data)}.`
  return (
    <div role="status" className={`border-b-2 ${tone}`}>
      <div className="mx-auto flex max-w-(--wide) flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2">
        <span className="font-semibold">{words}</span>
        <Link
          to="/kierownik/dostep"
          className="inline-flex min-h-(--touch) items-center font-semibold text-accent underline underline-offset-4"
        >
          {data.read_only ? 'Wpisz kod dostępu' : 'Dostęp i kod'}
        </Link>
      </div>
    </div>
  )
}
