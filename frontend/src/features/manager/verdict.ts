import type { VersionOut } from '../../api/generated/model'
import { shifts } from './words'

function things(n: number): string {
  return n === 1 ? '1 rzecz' : `${n} rzeczy`
}

/**
 * One plain sentence above the numbers: is this a good schedule, and how much is there to look at.
 * Holes and "no exceptions" problems come first, because the percentages mean little until they are fixed.
 */
export function verdict(data: VersionOut): string {
  const { scores } = data
  if (scores.hard_violations > 0) {
    return 'Ten grafik łamie zasady bez wyjątków. Popraw je, zanim go opublikujesz.'
  }
  if (scores.holes > 0) {
    return `Brakuje ludzi: ${shifts(scores.holes)} bez obsady. Sprawdź je w tabeli poniżej.`
  }
  const broken = data.rules.filter((r) => !r.hard && r.broken > 0).length
  const unmet = data.unmet_requests.filter((r) => r.kind !== 'unscored').length
  const toCheck = broken + unmet + scores.unscored_requests
  if (toCheck === 0) return 'Dobry grafik. Wszystkie zmiany obsadzone, zasady i prośby spełnione.'
  return `Dobry grafik. Wszystkie zmiany obsadzone. Do sprawdzenia: ${things(toCheck)}, opisane niżej.`
}
