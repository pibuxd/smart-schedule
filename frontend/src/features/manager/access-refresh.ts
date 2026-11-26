import type { SubscriptionOut } from '../../api/generated/model'

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * Milliseconds until the state can change. The API counts whole days left, rounded up, so `expiring_soon`,
 * `read_only` and the words change only when that count drops: at `ends_at` minus (days_left - 1) days.
 * At least a minute, so a device clock running ahead of the server does not ask over and over.
 */
export function untilNextChange(data: SubscriptionOut, now = Date.now()): number | false {
  if (data.read_only || !data.ends_at) return false
  const next = Date.parse(data.ends_at) - (data.days_left - 1) * DAY_MS
  return Math.min(Math.max(next - now + 1000, 60_000), DAY_MS)
}
