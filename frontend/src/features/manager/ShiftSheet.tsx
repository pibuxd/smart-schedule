import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Clock, Pin, PinOff, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type { CandidateOut, CheckOut, ShiftExplanationOut, SlotEventOut, VersionShiftOut } from '../../api/generated/model'
import {
  useAddScheduleSeat,
  useChangeAssignments,
  useCheckScheduleChanges,
  useExplainShift,
  usePinShift,
  useRemoveScheduleSeat,
} from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { Disclosure } from '../../components/ui/disclosure'
import { Sheet } from '../../components/ui/sheet'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { StateIcon } from '../availability/StateIcon'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { ClashQuestion } from './ClashQuestion'
import { percent } from './schedule-grid'
import { differenceText } from '../schedule/hours'
import { useManager } from './ManagerContext'
import { WorkedHoursForm } from './WorkedHours'
import { shortDay } from './words'

const WISH_LABEL: Record<CandidateOut['wish'], string> = {
  prefer: 'chętnie',
  neutral: 'mogę',
  cannot: 'nie mogę',
}

/**
 * One shift: why it has its person (or nobody), and everyone with the position: who can take it, what it costs
 * (calendar wish, hours, rules, the scores after the change) and who cannot, with the reason. In an editable draft
 * the manager puts someone in, leaves the shift empty, or pins the person so arranging again keeps them.
 */
export function ShiftSheet({
  versionId,
  locationId,
  shift,
  editable,
  published = false,
  onClose,
}: {
  versionId: string
  locationId: string
  shift: VersionShiftOut | null
  editable: boolean
  /** A published version: the manager can set the hours a person really works ("Zmień godziny"). */
  published?: boolean
  onClose: () => void
}) {
  return (
    <Sheet
      open={shift !== null}
      onOpenChange={(open) => !open && onClose()}
      title={shift ? `${shift.shift_type_name || 'Zmiana'} ${shift.start_time}–${shift.end_time}` : ''}
      description={shift ? `${shortDay(shift.date)}, ${shift.position_name}` : undefined}
    >
      {shift && (
        <ShiftDetails
          versionId={versionId}
          locationId={locationId}
          shift={shift}
          editable={editable}
          published={published}
          onDone={onClose}
        />
      )}
    </Sheet>
  )
}

function ShiftDetails({
  versionId,
  locationId,
  shift,
  editable,
  published,
  onDone,
}: {
  versionId: string
  locationId: string
  shift: VersionShiftOut
  editable: boolean
  published: boolean
  onDone: () => void
}) {
  const explanation = useExplainShift(versionId, shift.id)
  const change = useChangeAssignments()
  const checker = useCheckScheduleChanges()
  const pin = usePinShift()
  const addSeat = useAddScheduleSeat()
  const removeSeat = useRemoveScheduleSeat()
  const queryClient = useQueryClient()
  // The chosen person has another shift at the same time: the question waits for the manager's answer.
  const [question, setQuestion] = useState<{ employeeId: string; check: CheckOut } | null>(null)

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

  const togglePin = () =>
    pin.mutate(
      { versionId, shiftId: shift.id, data: { pinned: !shift.pinned } },
      {
        onSuccess: () => {
          refresh()
          onDone()
        },
      },
    )

  const saved = {
    onSuccess: () => {
      refresh()
      onDone()
    },
  }
  const addPlace = () =>
    shift.shift_type_id &&
    addSeat.mutate(
      { versionId, data: { date: shift.date, shift_type_id: shift.shift_type_id, position_id: shift.position_id } },
      saved,
    )

  const put = (employeeId: string | null, { force = false, removeClashes = false } = {}) =>
    change.mutate(
      {
        versionId,
        data: { changes: [{ shift_id: shift.id, employee_id: employeeId }], force, remove_clashes: removeClashes },
      },
      saved,
    )

  // Check first: when the person works elsewhere at the same time, ask before taking them off that shift.
  const choose = (employeeId: string) =>
    checker.mutate(
      { versionId, data: { changes: [{ shift_id: shift.id, employee_id: employeeId }] } },
      {
        onSuccess: (response) => {
          const check = response.data as CheckOut
          if (check.clashes.length > 0) setQuestion({ employeeId, check })
          else put(employeeId)
        },
      },
    )
  const busy = change.isPending || checker.isPending

  const asked = (candidate: CandidateOut) =>
    question?.employeeId === candidate.employee_id && (
      <ClashQuestion
        check={question.check}
        busy={busy}
        onMove={(force) => put(candidate.employee_id, { force, removeClashes: true })}
        onCancel={() => setQuestion(null)}
      />
    )

  return (
    <div className="grid gap-5">
      {shift.past && (
        <p className="m-0 text-ink-muted">
          {editable
            ? 'Ten dzień już minął. Popraw, jeśli pracował ktoś inny, żeby godziny się zgadzały.'
            : 'Ten dzień już minął. Żeby go poprawić, naciśnij „Popraw grafik”.'}
        </p>
      )}
      <section className="grid gap-2" aria-label="Wyjaśnienie przydziału">
        <h3 className="m-0 text-lg font-extrabold">{shift.employee_id ? 'Co uzasadnia ten przydział w obecnym grafiku?' : 'Dlaczego zmiana jest bez obsady?'}</h3>
        {shift.manual && shift.employee_id && <p className="m-0">Ten przydział zmieniono ręcznie.</p>}
        {shift.pinned && <p className="m-0">{shift.employee_id ? 'Przypięcie zachowuje tę osobę przy ponownym układaniu grafiku.' : 'Kierownik przypiął to miejsce jako puste.'}</p>}
        <p className="m-0">{data.summary}</p>
        {!!data.reasons?.length && (
          <div>
            <h4 className="m-0 text-base font-semibold">Skutek zmiany przy obecnych ustawieniach</h4>
            <ul className="my-1 grid gap-1 pl-5">
              {data.reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>
        )}
      </section>
      {data.shift.problems.map((problem) => (
        <InlineError key={problem}>{problem}</InlineError>
      ))}
      {data.shift.forced && (
        <div className="grid gap-1 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
          <span className="flex items-center gap-1.5 font-semibold">
            <ShieldAlert aria-hidden="true" size={18} /> Wpisane mimo przeszkód
          </span>
          {data.shift.overridden.map((problem) => (
            <span key={problem} className="text-sm">
              {problem}
            </span>
          ))}
        </div>
      )}

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
                onClick={togglePin}
              >
                {shift.pinned ? <PinOff aria-hidden="true" size={20} /> : <Pin aria-hidden="true" size={20} />}
                {shift.pinned ? 'Odepnij' : 'Przypnij tę osobę'}
              </Button>
              <Button variant="danger" size="normal" disabled={change.isPending} onClick={() => put(null)}>
                Zostaw bez obsady
              </Button>
            </div>
          )}
        </div>
      )}

      {published && shift.employee_id && shift.assignment_id && (
        <ShiftHours shift={shift} assignmentId={shift.assignment_id} onDone={onDone} />
      )}

      {!current && editable && (
        <div className="grid gap-2 rounded-md border-2 border-dashed border-line bg-surface p-3">
          <span className="font-semibold">Ta zmiana jest bez obsady.</span>
          <span className="text-sm text-ink-muted">
            {shift.pinned
              ? 'Przypięta jako pusta: gdy ułożysz grafik od nowa, nikt jej nie dostanie.'
              : 'Gdy ułożysz grafik od nowa, generator spróbuje ją obsadzić. Przypnij, jeśli ma zostać pusta.'}
          </span>
          <Button variant="secondary" size="normal" className="w-fit" disabled={pin.isPending} onClick={togglePin}>
            {shift.pinned ? <PinOff aria-hidden="true" size={20} /> : <Pin aria-hidden="true" size={20} />}
            {shift.pinned ? 'Odepnij' : 'Zostaw pustą na stałe'}
          </Button>
        </div>
      )}

      {!current && able.length === 0 && (
        <div className="grid gap-1 rounded-md border border-line bg-surface p-3">
          <span className="font-semibold">Nikt nie może wziąć tej zmiany.</span>
          <span className="text-sm">
            Każda osoba ma powód, np. dzień „nie mogę”, inną zmianę o tej porze albo zasadę bez wyjątków. Osobę z
            „nie mogę” albo zasadą możesz wpisać mimo to (lista niżej). Możesz też:
          </span>
          <ul className="m-0 grid gap-1 pl-5 text-sm">
            <li>usunąć to miejsce (przycisk niżej),</li>
            <li>
              <Link to="/kierownik/lokal/$locationId/zasady" params={{ locationId }} className="font-semibold text-accent">
                zmienić zasadę
              </Link>{' '}
              z „bez wyjątków” na zwykłą,
            </li>
            {editable && blocked.some((c) => c.clash) && (
              <li>przenieść tutaj kogoś, kto ma w tym czasie inną zmianę (przycisk przy tej osobie niżej),</li>
            )}
            <li>dodać komuś to stanowisko w „Pracownicy” albo zostawić zmianę pustą.</li>
          </ul>
          <span className="text-sm text-ink-muted">Powód przy każdej osobie jest niżej, w „Nie mogą wziąć tej zmiany”.</span>
        </div>
      )}

      {change.isError && <InlineError>{errorMessage(change.error, NETWORK_PROBLEM)}</InlineError>}
      {checker.isError && <InlineError>{errorMessage(checker.error, NETWORK_PROBLEM)}</InlineError>}
      {pin.isError && <InlineError>{errorMessage(pin.error, NETWORK_PROBLEM)}</InlineError>}

      {able.length > 0 && (
        <section className="grid gap-2">
          <h3 className="m-0 text-base font-extrabold">{current ? 'Mogą pracować zamiast' : 'Mogą wziąć tę zmianę'}</h3>
          <ul className="m-0 grid list-none gap-2 p-0">
            {able.map((candidate) => (
              <li key={candidate.employee_id} className="grid gap-2 rounded-md border border-line bg-surface p-3">
                <CandidateLine candidate={candidate} />
                {editable && !asked(candidate) && (
                  <Button size="normal" className="w-fit" disabled={busy} onClick={() => choose(candidate.employee_id)}>
                    Wpisz: {candidate.name}
                  </Button>
                )}
                {asked(candidate)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {blocked.length > 0 && (
        <Disclosure summary={`Nie mogą wziąć tej zmiany (${blocked.length})`} summaryClassName="font-semibold text-accent">
          <ul className="m-0 mt-2 grid list-none gap-2 p-0">
            {blocked.map((candidate) => (
              <li key={candidate.employee_id} className="grid gap-1 rounded-md border border-dashed border-line bg-surface p-3">
                <span className="font-semibold">{candidate.name}</span>
                {candidate.problems.map((problem) => (
                  <span key={problem} className="text-sm text-cannot">
                    {problem}
                  </span>
                ))}
                {editable && (candidate.clash || candidate.can_force) && !asked(candidate) && (
                  <Button
                    variant="secondary"
                    size="normal"
                    className="w-fit"
                    disabled={busy}
                    onClick={() =>
                      candidate.clash ? choose(candidate.employee_id) : put(candidate.employee_id, { force: true })
                    }
                  >
                    {candidate.clash ? (
                      `Przenieś tutaj: ${candidate.name}`
                    ) : (
                      <>
                        <ShieldAlert aria-hidden="true" size={20} />
                        Wpisz mimo to: {candidate.name}
                      </>
                    )}
                  </Button>
                )}
                {asked(candidate)}
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      {editable && (
        <section className="grid gap-2 rounded-md border border-line bg-surface p-3">
          <h3 className="m-0 text-base font-extrabold">Ile osób na tej zmianie</h3>
          <p className="m-0 text-sm text-ink-muted">Zmieniasz obsadę tylko tego dnia. Zostanie też, gdy ułożysz grafik od nowa.</p>
          <div className="flex flex-wrap gap-2">
            {shift.shift_type_id && (
              <Button variant="secondary" size="normal" disabled={addSeat.isPending || removeSeat.isPending} onClick={addPlace}>
                <Plus aria-hidden="true" size={20} />
                Dodaj miejsce
              </Button>
            )}
            <Button
              variant="danger"
              size="normal"
              disabled={addSeat.isPending || removeSeat.isPending}
              onClick={() => removeSeat.mutate({ versionId, shiftId: shift.id }, saved)}
            >
              <Trash2 aria-hidden="true" size={20} />
              {shift.employee_id ? `Usuń miejsce (${shift.employee_name} traci zmianę)` : 'Usuń to miejsce'}
            </Button>
          </div>
          {addSeat.isError && <InlineError>{errorMessage(addSeat.error, NETWORK_PROBLEM)}</InlineError>}
          {removeSeat.isError && <InlineError>{errorMessage(removeSeat.error, NETWORK_PROBLEM)}</InlineError>}
        </section>
      )}
      <SlotHistory events={data.history} />
    </div>
  )
}

/** Hours of the person on a published shift: what counts, a waiting report, and "Zmień godziny". */
function ShiftHours({ shift, assignmentId, onDone }: { shift: VersionShiftOut; assignmentId: string; onDone: () => void }) {
  const { readOnly } = useManager()
  const [open, setOpen] = useState(false)
  const range = (start: string, end: string) => `${start}–${end}`
  return (
    <section className="grid gap-2 rounded-md border border-line bg-surface p-3" aria-label="Godziny pracy">
      <h3 className="m-0 flex items-center gap-1.5 text-base font-extrabold">
        <Clock aria-hidden="true" size={18} /> Godziny pracy
      </h3>
      <p className="m-0">
        {shift.worked
          ? `Liczą się ${range(shift.worked.start_time, shift.worked.end_time)} zamiast ${range(shift.start_time, shift.end_time)} (${differenceText(shift.worked.difference_minutes)}).`
          : `Liczą się godziny z grafiku: ${range(shift.start_time, shift.end_time)}.`}
      </p>
      {shift.hours_report && !open && (
        <p className="m-0 font-semibold text-prefer-not">
          {shift.employee_name} zgłasza {range(shift.hours_report.start_time, shift.hours_report.end_time)} (
          {differenceText(shift.hours_report.difference_minutes)}). Zdecydujesz w „Godzinach” albo tutaj.
        </p>
      )}
      {open ? (
        <WorkedHoursForm
          target={{
            assignmentId,
            employeeId: shift.employee_id!,
            name: shift.employee_name,
            date: shift.date,
            plannedStart: shift.start_time,
            plannedEnd: shift.end_time,
            worked: shift.worked,
            report: shift.hours_report,
          }}
          onDone={onDone}
        />
      ) : (
        <div>
          <Button variant="secondary" size="normal" disabled={readOnly} onClick={() => setOpen(true)}>
            Zmień godziny
          </Button>
        </div>
      )}
    </section>
  )
}

const REASON_LABEL: Record<SlotEventOut['reason'], string> = {
  generated: 'ułożone automatycznie',
  manual: 'zmiana ręczna',
  offer: 'oddana zmiana',
  swap: 'zamiana',
}

/** Who held this shift before: published changes and given-away shifts, newest first. */
function SlotHistory({ events }: { events: SlotEventOut[] }) {
  if (events.length === 0) return null
  return (
    <Disclosure boxed summary={`Historia tej zmiany (${events.length})`} summaryClassName="font-semibold">
      <ol className="m-0 grid list-none gap-2 p-0">
        {events.map((event) => (
          <li key={`${event.at}-${event.to_name}`} className="grid gap-0.5 border-t border-grid pt-2 first:border-t-0">
            <span>
              {event.from_name || 'nikt'} → <b>{event.to_name || 'bez obsady'}</b>
            </span>
            <span className="text-sm text-ink-muted">
              {REASON_LABEL[event.reason]}, {dateTimeText(event.at)}
              {event.by_name ? `, ${event.by_name}` : ''}
            </span>
          </li>
        ))}
      </ol>
    </Disclosure>
  )
}

function dateTimeText(iso: string): string {
  return new Date(iso).toLocaleString('pl-PL', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })
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
