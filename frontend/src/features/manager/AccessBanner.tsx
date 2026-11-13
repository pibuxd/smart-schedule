import { Link } from '@tanstack/react-router'

import { useSubscription } from '../../api/generated/billing/billing'
import type { SubscriptionOut } from '../../api/generated/model'
import { statusWords } from './words'

/** A strip at the top of the manager's panel: read-only mode, the trial, or access ending within 7 days. */
export function AccessBanner({ companyId }: { companyId: string }) {
  const subscription = useSubscription(companyId, { query: { staleTime: 60_000 } })
  if (!subscription.isSuccess) return null
  const data = subscription.data.data as SubscriptionOut
  if (!data.read_only && !data.trial && !data.expiring_soon) return null
  const tone = data.read_only ? 'border-cannot bg-cannot-soft text-cannot' : 'border-accent bg-accent-soft text-ink'
  const words = data.read_only
    ? data.trial
      ? 'Okres próbny minął: grafiki można oglądać, ale nie zmieniać.'
      : 'Grafiki można teraz tylko oglądać.'
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
