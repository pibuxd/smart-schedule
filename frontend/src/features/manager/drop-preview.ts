import type { CheckOut, VersionShiftOut } from '../../api/generated/model'
import { percent } from './schedule-grid'

/** The answer for one drop: known, not known yet (`undefined`), or the check did not work. */
export type DropCheck = CheckOut | 'failed' | undefined

export type DropWords = { what: string | null; verdict: string | null; bad: boolean }

/** Can the dragged person be dropped on `target` at all (another shift, of another person or empty)? */
export function isDropTarget(dragged: VersionShiftOut, target: VersionShiftOut | undefined): target is VersionShiftOut {
  return !!target && target.id !== dragged.id && target.employee_id !== dragged.employee_id
}

/**
 * What dropping here would do, while the person is being dragged. `what` needs no answer from the server, so it
 * is there at once; `verdict` appears as soon as the check is known (never a "checking…" placeholder).
 */
export function dropWords(dragged: VersionShiftOut, target: VersionShiftOut | undefined, check: DropCheck): DropWords {
  if (!isDropTarget(dragged, target)) return { what: 'Upuść na innej zmianie, żeby zamienić osoby.', verdict: null, bad: false }
  const what = target.employee_id ? `Zamiana z: ${target.employee_name}` : 'Przeniesienie na zmianę bez obsady'
  if (check === undefined) return { what, verdict: null, bad: false }
  if (check === 'failed') return { what, verdict: 'Nie udało się sprawdzić tej zamiany.', bad: true }
  // Another shift at the same time: dropping asks whether to take the person off it.
  const clash = check.clashes.find((c) => !c.can_remove) ?? check.clashes[0]
  if (clash) {
    if (!clash.can_remove) return { what, verdict: `${clash.text} ${clash.reason}`, bad: true }
    if (check.ok_if_removed) return { what, verdict: `${clash.text} Upuść, a zapytamy, czy ją stamtąd zdjąć.`, bad: false }
    const problem = check.problems_if_removed[0] ?? clash.text
    return { what, verdict: check.can_force_if_removed ? `${problem} Upuść, jeśli chcesz zapisać mimo to.` : problem, bad: true }
  }
  if (!check.ok) {
    const problem = check.problems[0] ?? 'Ta zamiana łamie zasady.'
    return { what, verdict: check.can_force ? `${problem} Upuść, jeśli chcesz zapisać mimo to.` : problem, bad: true }
  }
  const after = check.after
  return { what, verdict: `Można. Zasady ${percent(after.manager_rules)}, prośby ${percent(after.employee_requests)}.`, bad: false }
}
