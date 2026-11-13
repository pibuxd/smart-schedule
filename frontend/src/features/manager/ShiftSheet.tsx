import { useQueryClient } from '@tanstack/react-query'
import { Pin, PinOff } from 'lucide-react'

import type { CandidateOut, ShiftExplanationOut, VersionShiftOut } from '../../api/generated/model'
import { useChangeAssignments, useExplainShift, usePinShift } from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { StateIcon } from '../availability/StateIcon'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { percent } from './schedule-grid'
import { shortDay } from './words'

const WISH_LABEL: Record<CandidateOut['wish'], string> = {
  prefer: 'chętnie',
  neutral: 'bez zaznaczenia',
  cannot: 'nie mogę',
}

/**
 * One shift: why it has its person (or nobody), and everyone with the position: who can take it, what it costs
 * (calendar wish, hours, rules, the scores after the change) and who cannot, with the reason. In an editable draft
 * the manager puts someone in, leaves the shift empty, or pins the person so arranging again keeps them.
 */
export function ShiftSheet({
  versionId,
  shift,
  editable,
  onClose,
}: {
  versionId: string
  shift: VersionShiftOut | null
  editable: boolean
  onClose: () => void
}) {
  return (
    <Sheet
      open={shift !== null}
      onOpenChange={(open) => !open && onClose()}
      title={shift ? `${shift.shift_type_name || 'Zmiana'} ${shift.start_time}–${shift.end_time}` : ''}
      description={shift ? `${shortDay(shift.date)}, ${shift.position_name}` : undefined}
    >
      {shift && <ShiftDetails versionId={versionId} shift={shift} editable={editable && !shift.past} onDone={onClose} />}
    </Sheet>
  )
}

function ShiftDetails({
  versionId,
  shift,
  editable,
  onDone,
}: {
  versionId: string
  shift: VersionShiftOut
  editable: boolean
  onDone: () => void
}) {
  const explanation = useExplainShift(versionId, shift.id)
  const change = useChangeAssignments()
  const pin = usePinShift()
  const queryClient = useQueryClient()

  if (explanation.isPending) return <Loading>Sprawdzam, kto może wziąć tę zmianę…</Loading>
  if (explanation.isError) {
    return (
      <ErrorState onRetry={() => void explanation.refetch()}>
        {errorMessage(explanation.error, 'Nie udało się sprawdzić tej zmiany. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = explanation.data.data as ShiftExplanationOut
  const current = data.candidates.find((c) => c.current)
  const others = data.candidates.filter((c) => !c.current)
  const able = others.filter((c) => c.possible)
  const blocked = others.filter((c) => !c.possible)
  const refresh = () => void queryClient.invalidateQueries()

  const put = (employeeId: string | null) =>
    change.mutate(
      { versionId, data: { changes: [{ shift_id: shift.id, employee_id: employeeId }] } },
      {
        onSuccess: () => {
          refresh()
          onDone()
        },
      },
    )

  return (
    <div className="grid gap-5">
      {shift.past && <p className="m-0 text-ink-muted">Ten dzień już minął, więc tej zmiany nie można zmienić.</p>}
      <p className="m-0">{data.summary}</p>
      {data.shift.problems.map((problem) => (
        <InlineError key={problem}>{problem}</InlineError>
      ))}

      {current && (
        <div className="grid gap-2 rounded-md border-2 border-ink bg-surface p-3">
          <span className="text-sm font-semibold text-ink-muted">Na tej zmianie</span>
          <CandidateLine candidate={current} />
          {editable && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="normal"
                disabled={pin.isPending}
                onClick={() =>
                  pin.mutate(
                    { versionId, shiftId: shift.id, data: { pinned: !shift.pinned } },
                    {
                      onSuccess: () => {
                        refresh()
                        onDone()
                      },
                    },
                  )
                }
              >
                {shift.pinned ? <PinOff aria-hidden="true" size={20} /> : <Pin aria-hidden="true" size={20} />}
                {shift.pinned ? 'Odepnij' : 'Przypnij tę osobę'}
              </Button>
              <Button variant="danger" size="normal" disabled={change.isPending} onClick={() => put(null)}>
                Zostaw bez obsady
              </Button>
            </div>
          )}
          {shift.pinned && (
            <p className="m-0 text-sm text-ink-muted">Przypięta: przy ponownym układaniu ta osoba zostanie na tej zmianie.</p>
          )}
        </div>
      )}

      {change.isError && <InlineError>{errorMessage(change.error, NETWORK_PROBLEM)}</InlineError>}
      {pin.isError && <InlineError>{errorMessage(pin.error, NETWORK_PROBLEM)}</InlineError>}

      {able.length > 0 && (
        <section className="grid gap-2">
          <h3 className="m-0 text-base font-extrabold">{current ? 'Mogą pracować zamiast' : 'Mogą wziąć tę zmianę'}</h3>
          <ul className="m-0 grid list-none gap-2 p-0">
            {able.map((candidate) => (
              <li key={candidate.employee_id} className="grid gap-2 rounded-md border border-line bg-surface p-3">
                <CandidateLine candidate={candidate} />
                {editable && (
                  <Button size="normal" className="w-fit" disabled={change.isPending} onClick={() => put(candidate.employee_id)}>
                    Wpisz: {candidate.name}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {blocked.length > 0 && (
        <details className="grid gap-2">
          <summary className="min-h-(--touch) cursor-pointer content-center font-semibold text-accent">
            Nie mogą wziąć tej zmiany ({blocked.length})
          </summary>
          <ul className="m-0 mt-2 grid list-none gap-2 p-0">
            {blocked.map((candidate) => (
              <li key={candidate.employee_id} className="grid gap-1 rounded-md border border-dashed border-line bg-surface p-3">
                <span className="font-semibold">{candidate.name}</span>
                {candidate.problems.map((problem) => (
                  <span key={problem} className="text-sm text-cannot">
                    {problem}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function CandidateLine({ candidate }: { candidate: CandidateOut }) {
  const hours = `${String(candidate.hours).replace('.', ',')} h w grafiku`
  const target = candidate.target_hours ? `, cel ${candidate.target_hours} h` : ''
  const over = candidate.max_hours !== null && candidate.hours > candidate.max_hours
  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold">{candidate.name}</span>
        <span className={`avail-${candidate.wish} inline-flex items-center gap-1 rounded-sm border px-1.5 text-sm font-semibold`}>
          <StateIcon state={candidate.wish} size={16} />
          {WISH_LABEL[candidate.wish]}
        </span>
        <span className={`text-sm ${over ? 'font-semibold text-cannot' : 'text-ink-muted'}`}>
          {hours}
          {target}
          {over ? `, ponad maksimum ${candidate.max_hours} h` : ''}
        </span>
      </div>
      {candidate.notes.map((note) => (
        <span key={note} className="text-sm text-prefer-not">
          {note}
        </span>
      ))}
      {!candidate.current && (
        <span className="text-sm text-ink-muted">
          Po zmianie: zasady {percent(candidate.manager_rules)}, prośby {percent(candidate.employee_requests)}
          {candidate.holes > 0 ? `, bez obsady: ${candidate.holes}` : ''}
        </span>
      )}
    </div>
  )
}
