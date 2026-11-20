import type { VersionOut } from '../../api/generated/model'
import { shifts } from './words'

function things(n: number): string {
  return n === 1 ? '1 rzecz' : `${n} rzeczy`
}

/**
 * One plain sentence above the numbers: are all shifts covered, and how much is there to look at.
 * Holes and "no exceptions" problems come first, because the percentages mean little until they are fixed.
 */
export function verdict(data: VersionOut): string {
  const { scores } = data
  if (data.hard_problems.length > 0) {
    return 'Ten grafik łamie zasady bez wyjątków. Popraw je, zanim go opublikujesz.'
  }
  if (scores.holes > 0) {
    return `Brakuje ludzi: ${shifts(scores.holes)} bez obsady. Sprawdź je w tabeli poniżej.`
  }
  // A soft rule kept only in part (an hours target at 95 %) is not "spełniona", even without a counted break.
  const broken = data.rules.filter((r) => !r.hard && (r.broken > 0 || (r.percent != null && r.percent < 100))).length
  // The list of employee requests is cut on the server; the count is not. The manager's instructions are all listed.
  const orders = data.unmet_requests.filter((r) => r.kind === 'instruction').length
  const unmet = orders + (data.unmet_request_count ?? data.unmet_requests.filter((r) => r.kind !== 'unscored').length - orders)
  const toCheck = broken + unmet + scores.unscored_requests
  if (toCheck === 0) return 'Wszystkie zmiany obsadzone, zasady i prośby spełnione.'
  return `Wszystkie zmiany obsadzone. Do sprawdzenia: ${things(toCheck)}, opisane niżej.`
}
