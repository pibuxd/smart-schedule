import { useId } from 'react'

import type { CheckOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { InlineError } from '../../components/ui/status'

/**
 * The person has another shift at the same time (here, or in a draft or the published schedule of another location).
 * The manager decides: take the person off it (it becomes an empty shift) and put them here, or leave things as they
 * are. When that is not possible, says why (another manager's location, a shift that has started, a rule).
 */
export function ClashQuestion({
  check,
  busy,
  onMove,
  onCancel,
}: {
  check: CheckOut
  busy: boolean
  onMove: () => void
  onCancel: () => void
}) {
  const titleId = useId()
  const several = check.clashes.length > 1
  const blocked = check.clashes.some((c) => !c.can_remove)
  const published = check.clashes.some((c) => c.kind === 'published')
  return (
    <div role="alertdialog" aria-labelledby={titleId} className="grid gap-2 rounded-md border-2 border-ink bg-surface p-3">
      <span id={titleId} className="font-semibold">
        {several ? 'Ta osoba ma w tym czasie inne zmiany' : 'Ta osoba ma w tym czasie inną zmianę'}
      </span>
      <ul className="m-0 grid gap-1 pl-5">
        {check.clashes.map((clash) => (
          <li key={clash.shift_id}>
            {clash.text}
            {!clash.can_remove && <span className="block text-sm font-semibold text-cannot">{clash.reason}</span>}
          </li>
        ))}
      </ul>
      {check.ok_if_removed ? (
        <>
          <p className="m-0">
            Na pewno chcesz to zmienić?{' '}
            {several
              ? 'Zdejmiemy tę osobę z tamtych zmian, a one zostaną puste.'
              : 'Zdejmiemy tę osobę z tamtej zmiany, a ona zostanie pusta.'}
            {published ? ' Damy znać tej osobie i kierownikowi tamtego lokalu.' : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="normal" disabled={busy} onClick={onMove}>
              Tak, przenieś tutaj
            </Button>
            <Button variant="secondary" size="normal" disabled={busy} onClick={onCancel}>
              Zostaw jak jest
            </Button>
          </div>
        </>
      ) : (
        <>
          {!blocked && (
            <>
              <p className="m-0">Nawet bez tamtej zmiany ta zmiana złamie zasady:</p>
              {check.problems_if_removed.map((problem) => (
                <InlineError key={problem}>{problem}</InlineError>
              ))}
            </>
          )}
          <Button variant="secondary" size="normal" className="w-fit" onClick={onCancel}>
            Zamknij
          </Button>
        </>
      )}
    </div>
  )
}
