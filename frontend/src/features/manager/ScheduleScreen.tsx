import {
  DndContext,
  type DragEndEvent,
  type DragOverEvent,
  DragOverlay,
  type DragStartEvent,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarPlus, Clock, Hand, Pin, Plus, Send, ShieldAlert, SquarePen, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'

import type {
  CheckOut,
  DropCheckOut,
  PeriodOut,
  ScoresOut,
  ShiftFitOut,
  VersionOut,
  VersionShiftOut,
} from '../../api/generated/model'
import {
  getLocationPeriodsQueryKey,
  useAddScheduleSeat,
  useChangeAssignments,
  useCheckScheduleChanges,
  useDeleteScheduleDraft,
  useEmployeeFit,
  useLocationPeriods,
  usePinShift,
  usePublishSchedule,
  useScheduleVersion,
  useShiftDropChecks,
  useStartCorrecting,
} from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { ConfirmSheet } from '../../components/ui/confirm'
import { Disclosure } from '../../components/ui/disclosure'
import { Section, SelectField, Tag } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import { StateIcon } from '../availability/StateIcon'
import { dayAndMonth, parseDate, weekdayIndex, weekdayShort } from '../../lib/dates'
import { ArrangeButton, RunProgress } from './ArrangeSchedule'
import { useManager } from './ManagerContext'
import { pickPeriod } from './periods'
import { ClashQuestion } from './ClashQuestion'
import { type DropCheck, dropWords, isDropTarget } from './drop-preview'
import { buildGrid, type GridColumn, percent, swapChanges } from './schedule-grid'
import { ShiftSheet } from './ShiftSheet'
import { verdict } from './verdict'
import { countWords, daysUntil, PERIOD_STATUS, periodTitle, shifts as shiftsWord } from './words'

const VERSION_STATUS: Record<VersionOut['status'], string> = {
  draft: 'Szkic',
  published: 'Opublikowany',
  superseded: 'Starsza wersja',
}

/** "Grafik" of one location: arrange it, look at the result with its scores, correct it and publish it. */
export function ScheduleScreen({ locationId, today = new Date() }: { locationId: string; today?: Date }) {
  const periods = useLocationPeriods(locationId)
  const [chosen, setChosen] = useState<string | null>(null)

  if (periods.isPending) return <Loading>Wczytuję okresy grafiku…</Loading>
  if (periods.isError) {
    return (
      <ErrorState onRetry={() => void periods.refetch()}>
        {errorMessage(periods.error, 'Nie udało się wczytać okresów grafiku. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const list = periods.data.data as PeriodOut[]
  const period = list.find((p) => p.id === chosen) ?? pickPeriod(list, today)
  if (!period) {
    return (
      <EmptyState title="Nie ma jeszcze okresu grafiku">
        <p className="m-0">Najpierw ustal daty grafiku i termin dyspozycji w zakładce „Dyspozycje”.</p>
        <Link
          to="/kierownik/lokal/$locationId/dyspozycje"
          params={{ locationId }}
          className="inline-flex min-h-(--touch) items-center gap-2 font-semibold text-accent underline underline-offset-4"
        >
          <CalendarPlus aria-hidden="true" size={20} />
          Przejdź do dyspozycji
        </Link>
      </EmptyState>
    )
  }

  return (
    <div className="grid gap-6">
      {list.length > 1 && (
        <SelectField label="Okres grafiku" value={period.id} onChange={(e) => setChosen(e.target.value)} className="max-w-sm">
          {[...list]
            .sort((a, b) => b.start.localeCompare(a.start))
            .map((p) => (
              <option key={p.id} value={p.id}>
                {periodTitle(p.start, p.end)} ({PERIOD_STATUS[p.status].toLowerCase()})
              </option>
            ))}
        </SelectField>
      )}
      <PeriodSchedule key={period.id} period={period} locationId={locationId} today={today} />
    </div>
  )
}

function PeriodSchedule({ period, locationId, today }: { period: PeriodOut; locationId: string; today: Date }) {
  const { readOnly } = useManager()
  const [viewing, setViewing] = useState<string | null>(null)
  const versionId = viewing ?? period.latest_version_id
  const target = {
    periodId: period.id,
    locationId,
    locationName: 'ten lokal',
    missing: period.missing_availability,
    deadlinePassed: daysUntil(period.deadline, today) < 0,
    manualChanges: period.manual_changes,
    hasVersion: period.latest_version_id !== null,
    experiencedShort: period.experienced_short,
  }

  return (
    <div className="grid gap-6">
      <section className="flex flex-wrap items-start justify-between gap-4 rounded-md border border-line bg-surface p-4">
        <div className="grid gap-1">
          <h2 className="m-0 text-xl font-extrabold">Grafik {periodTitle(period.start, period.end)}</h2>
          <span>
            <Tag tone={period.status === 'published' ? 'accent' : 'muted'}>{PERIOD_STATUS[period.status]}</Tag>
          </span>
          {period.status === 'collecting' && (
            <p className="m-0 text-sm text-ink-muted">
              Dyspozycji nie wysłało jeszcze: {period.missing_availability}.
            </p>
          )}
        </div>
        <div className="grid justify-items-start gap-2 sm:justify-items-end">
          {period.active_run_id ? (
            <RunProgress runId={period.active_run_id} />
          ) : (
            <ArrangeButton
              targets={[target]}
              disabled={readOnly}
              variant={period.latest_version_id ? 'secondary' : 'primary'}
              onStarted={() => setViewing(null)}
            />
          )}
          {period.latest_version_id && !period.active_run_id && (
            <span className="max-w-[40ch] text-sm text-ink-muted sm:text-right">
              „Ułóż od nowa” zostawia przypięte zmiany, osoby wpisane mimo przeszkód i minione dni.
            </span>
          )}
        </div>
      </section>

      {versionId ? (
        <VersionView
          key={versionId}
          versionId={versionId}
          onShowVersion={(id) => setViewing(id && id !== period.latest_version_id ? id : null)}
        />
      ) : (
        !period.active_run_id && (
          <EmptyState title="Grafik nie jest jeszcze ułożony">
            <p className="m-0">
              Naciśnij „Ułóż grafik”, gdy minie termin dyspozycji albo wszyscy je wyślą.
            </p>
          </EmptyState>
        )
      )}
    </div>
  )
}

function VersionView({ versionId, onShowVersion }: { versionId: string; onShowVersion: (id: string | null) => void }) {
  const version = useScheduleVersion(versionId)
  if (version.isPending) return <Loading>Wczytuję grafik…</Loading>
  if (version.isError) {
    return (
      <ErrorState onRetry={() => void version.refetch()}>
        {errorMessage(version.error, 'Nie udało się wczytać grafiku. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = version.data.data as VersionOut
  return (
    <div className="grid gap-6">
      <VersionHeader data={data} onShowVersion={onShowVersion} />
      <p className="m-0 text-lg font-semibold">{verdict(data)}</p>
      <Scores scores={data.scores} />
      {data.hard_problems.length > 0 && (
        <div role="alert" className="grid gap-1 rounded-md border border-cannot bg-cannot-soft p-3 text-cannot">
          <span className="font-semibold">Tego grafiku nie można opublikować, bo łamie zasady:</span>
          {data.hard_problems.map((p) => (
            <span key={p}>{p}</span>
          ))}
        </div>
      )}
      {data.accepted_problems.length > 0 && (
        <div className="grid gap-1 rounded-md border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
          <span className="font-semibold">Ręczne zmiany są niezgodne z obsadą. Możesz tak opublikować:</span>
          {data.accepted_problems.map((p) => (
            <span key={p}>{p}</span>
          ))}
        </div>
      )}
      {data.editable && <UnpinnedChanges data={data} />}
      <ScheduleGrid data={data} />
      <div className="grid gap-6 lg:grid-cols-2">
        <PeopleHours data={data} />
        <div className="grid content-start gap-6">
          <UnmetOrders data={data} />
          <div className="grid gap-2">
            <RulesList data={data} />
            <UnmetRequests data={data} />
          </div>
          {data.notes.length > 0 && (
            <section className="grid gap-2">
              <h2 className="m-0 text-lg font-extrabold">Uwagi</h2>
              {data.notes.map((note) => (
                <p key={note} className="m-0 text-sm text-ink-muted">
                  {note}
                </p>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

function VersionHeader({ data, onShowVersion }: { data: VersionOut; onShowVersion: (id: string | null) => void }) {
  const { readOnly } = useManager()
  const correct = useStartCorrecting()
  const queryClient = useQueryClient()
  const [publishing, setPublishing] = useState(false)
  const newest = data.history[0]
  const isNewest = newest?.id === data.id

  return (
    <section className="flex flex-wrap items-end justify-between gap-4">
      <div className="grid gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="m-0 text-lg font-extrabold">Wersja {data.number}</h2>
          <Tag tone={data.status === 'published' ? 'accent' : data.status === 'draft' ? 'warn' : 'muted'}>
            {VERSION_STATUS[data.status]}
          </Tag>
        </div>
        {data.status !== 'published' && (
          <span className="text-sm text-ink-muted">
            {data.status === 'draft' ? 'Pracownicy jeszcze tego nie widzą.' : 'Starsza wersja, tylko do podglądu.'}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {data.history.length > 1 && (
          <SelectField label="Wersje" value={data.id} onChange={(e) => onShowVersion(e.target.value)}>
            {data.history.map((v) => (
              <option key={v.id} value={v.id}>
                {`Wersja ${v.number}: ${VERSION_STATUS[v.status].toLowerCase()}${v.generated ? '' : ', poprawiona ręcznie'}`}
              </option>
            ))}
          </SelectField>
        )}
        {data.editable && !data.period.active_run_id && <DeleteDraft data={data} />}
        {data.editable && (
          <Button size="normal" onClick={() => setPublishing(true)} disabled={data.hard_problems.length > 0}>
            <Send aria-hidden="true" size={20} />
            Opublikuj
          </Button>
        )}
        {data.status === 'published' && isNewest && !readOnly && (
          <Button
            variant="secondary"
            size="normal"
            disabled={correct.isPending}
            onClick={() =>
              correct.mutate(
                { versionId: data.id },
                {
                  onSuccess: () => {
                    void queryClient.invalidateQueries()
                    onShowVersion(null)
                  },
                },
              )
            }
          >
            <SquarePen aria-hidden="true" size={20} />
            Popraw grafik
          </Button>
        )}
      </div>
      {correct.isError && <InlineError>{errorMessage(correct.error, NETWORK_PROBLEM)}</InlineError>}
      <PublishSheet data={data} open={publishing} onOpenChange={setPublishing} />
    </section>
  )
}

/** What is current after "Usuń szkic": the version just before this draft, if any. */
function versionBefore(data: VersionOut) {
  return data.history.filter((v) => v.number < data.number).sort((x, y) => y.number - x.number)[0]
}

/** "Usuń szkic": only this draft goes; the version before it is current again, else the period collects availability. */
function DeleteDraft({ data }: { data: VersionOut }) {
  const remove = useDeleteScheduleDraft()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const before = versionBefore(data)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Usuń szkic"
        title="Usuń szkic"
        className="inline-flex min-h-(--touch) min-w-(--touch) cursor-pointer items-center justify-center rounded-md text-cannot hover:bg-cannot-soft"
      >
        <Trash2 aria-hidden="true" size={22} />
      </button>
      <ConfirmSheet
        open={open}
        onOpenChange={setOpen}
        title="Usunąć szkic grafiku?"
        confirmLabel="Tak, usuń szkic"
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(
            { versionId: data.id },
            {
              onSuccess: async () => {
                // The periods first, so this draft's view is gone before its own data is asked for again.
                await queryClient.invalidateQueries({ queryKey: getLocationPeriodsQueryKey(data.location_id) })
                void queryClient.invalidateQueries()
              },
            },
          )
        }
      >
        <p className="m-0">
          {!before
            ? 'Szkic zniknie na dobre razem z poprawkami, a okres wróci do zbierania dyspozycji.'
            : before.published_at
              ? 'Szkic zniknie na dobre razem z poprawkami. Zostaje opublikowany grafik, który widzą pracownicy.'
              : `Szkic zniknie na dobre razem z poprawkami. Wróci poprzedni szkic, wersja ${before.number}.`}
        </p>
        <p className="m-0">Obsada dni i zmiany w grafikach innych lokali zostają.</p>
      </ConfirmSheet>
    </>
  )
}

/** Manual changes are dropped when the schedule is arranged again, unless pinned: say so and pin them in one go. */
function UnpinnedChanges({ data }: { data: VersionOut }) {
  const pin = usePinShift()
  const queryClient = useQueryClient()
  const [pinning, setPinning] = useState(false)
  const unpinned = data.shifts.filter((s) => s.manual && !s.pinned && s.employee_id)
  if (unpinned.length === 0) return null
  const pinAll = async () => {
    setPinning(true)
    try {
      for (const shift of unpinned) {
        await pin.mutateAsync({ versionId: data.id, shiftId: shift.id, data: { pinned: true } })
      }
    } finally {
      setPinning(false)
      void queryClient.invalidateQueries()
    }
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
      <p className="m-0">
        Ręczne poprawki bez przypięcia: {unpinned.length}. Znikną, jeśli ułożysz grafik od nowa. Przypięte zostaną na
        miejscu.
      </p>
      <Button variant="secondary" size="normal" disabled={pinning} onClick={() => void pinAll()}>
        <Pin aria-hidden="true" size={20} />
        {pinning ? 'Przypinam…' : `Przypnij poprawki (${unpinned.length})`}
      </Button>
      {pin.isError && <InlineError>{errorMessage(pin.error, NETWORK_PROBLEM)}</InlineError>}
    </div>
  )
}

function PublishSheet({ data, open, onOpenChange }: { data: VersionOut; open: boolean; onOpenChange: (o: boolean) => void }) {
  const publish = usePublishSchedule()
  const queryClient = useQueryClient()
  const holes = data.scores.holes
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Opublikować grafik?">
      <div className="grid gap-4">
        <p className="m-0">
          Pracownicy od razu zobaczą swoje zmiany w „Mój grafik”.
          {data.period.published_version_id ? ' Poprzednia wersja zostanie w historii.' : ''}
        </p>
        {data.changed_people.length > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
            Zmieniasz zmiany tych osób: {data.changed_people.join(', ')}. Dostaną powiadomienie, ale
            powiedz im też sam, bo mogły już coś zaplanować.
          </p>
        )}
        {holes > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-cannot bg-cannot-soft px-3 py-2">
            W grafiku są dziury: {shiftsWord(holes)} bez obsady. Możesz go opublikować i obsadzić te zmiany później.
          </p>
        )}
        {publish.isError && <InlineError>{errorMessage(publish.error, NETWORK_PROBLEM)}</InlineError>}
        <Button
          wide
          disabled={publish.isPending}
          onClick={() =>
            publish.mutate(
              { versionId: data.id },
              {
                onSuccess: () => {
                  void queryClient.invalidateQueries()
                  onOpenChange(false)
                },
              },
            )
          }
        >
          {publish.isPending ? 'Publikuję…' : holes > 0 ? 'Opublikuj mimo braków' : 'Opublikuj grafik'}
        </Button>
      </div>
    </Sheet>
  )
}

/** The three numbers: unfilled shifts, manager's rules, employees' requests. An incomplete schedule never looks good. */
function Scores({ scores }: { scores: ScoresOut }) {
  const incomplete = scores.holes > 0
  return (
    <section aria-label="Ocena grafiku" className="grid gap-3 sm:grid-cols-3">
      <div
        className={cn(
          'grid content-start gap-0.5 rounded-md border-2 px-3 py-2',
          incomplete ? 'border-cannot bg-cannot-soft text-cannot' : 'border-line bg-surface',
        )}
      >
        <span className="text-sm font-semibold">Zmiany bez obsady</span>
        <span className="text-xl font-extrabold">
          {scores.holes} <span className="text-base font-semibold">z {scores.slots}</span>
        </span>
        <span className="text-sm">{incomplete ? 'Nie wszystkie zmiany są obsadzone.' : 'Wszystkie zmiany obsadzone.'}</span>
      </div>
      <ScoreBox
        label="Zasady kierownika"
        value={scores.manager_rules}
        muted={incomplete}
        note={scores.unmeasured_rules > 0 ? `Zasady bez niczego do oceny: ${scores.unmeasured_rules}.` : undefined}
      />
      <ScoreBox
        label="Prośby pracowników"
        value={scores.employee_requests}
        muted={incomplete}
        note={scores.unscored_requests > 0 ? `Do Twojej oceny: ${scores.unscored_requests}.` : undefined}
      />
    </section>
  )
}

function ScoreBox({ label, value, muted, note }: { label: string; value: number; muted: boolean; note?: string }) {
  return (
    <div className="grid content-start gap-0.5 rounded-md border-2 border-line bg-surface px-3 py-2">
      <span className="text-sm font-semibold text-ink-muted">{label}</span>
      <span className={cn('text-xl font-extrabold', muted ? 'text-ink-muted' : 'text-ink')}>{percent(value)}</span>
      {note && <span className="text-sm text-ink-muted">{note}</span>}
    </div>
  )
}

// ----------------------------------------------------------------------------------------------- the grid

type Change = { shift_id: string; employee_id: string | null }
/** A change that breaks a hard rule, waiting for the manager's "save anyway". */
type Override = { changes: Change[]; problems: string[]; done: string }

/** How long the answers for one dragged person are reused; every saved change marks them stale anyway. */
const DROPS_FRESH_MS = 30_000

function ScheduleGrid({ data }: { data: VersionOut }) {
  const { columns, rows } = useMemo(() => buildGrid(data.shifts, data.period.start, data.period.end), [data])
  const byId = useMemo(() => new Map(data.shifts.map((s) => [s.id, s])), [data])
  const [open, setOpen] = useState<VersionShiftOut | null>(null)
  const [dragging, setDragging] = useState<VersionShiftOut | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  // Answers for single drops of this drag, used until the answer for all shifts arrives.
  const [singles, setSingles] = useState<Record<string, DropCheck>>({})
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)
  const [picked, setPicked] = useState('')
  const [override, setOverride] = useState<Override | null>(null)
  // Dropped on a shift while the person works elsewhere at the same time: the question waits for the manager.
  const [question, setQuestion] = useState<{ changes: Change[]; done: string; check: CheckOut } | null>(null)
  const checker = useCheckScheduleChanges()
  const change = useChangeAssignments()
  const addSeat = useAddScheduleSeat()
  const queryClient = useQueryClient()
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))
  const editable = data.editable
  // The person whose calendar colours the grid: the one being dragged, else the one picked from the list.
  const personId = dragging?.employee_id ?? picked
  // While dragged, the person leaves their shift, so it does not block other shifts at that time.
  const fit = useEmployeeFit(data.id, personId, dragging ? { moving_shift_id: dragging.id } : undefined, {
    query: { enabled: editable && !!personId },
  })
  const fitByShift = useMemo(
    () => new Map(personId && fit.data ? (fit.data.data as ShiftFitOut[]).map((f) => [f.shift_id, f]) : []),
    [fit.data, personId],
  )
  const template = `120px repeat(${columns.length}, minmax(0, 1fr))`

  // When a drag starts, one request works out every possible drop, so hovering over a shift needs no request.
  const drops = useShiftDropChecks(data.id, dragging?.id ?? '', {
    query: { enabled: !!dragging, staleTime: DROPS_FRESH_MS, retry: false },
  })
  const allDrops = useMemo(
    () => (drops.data ? new Map((drops.data.data as DropCheckOut[]).map((d) => [d.shift_id, d])) : null),
    [drops.data],
  )
  const target = overId ? byId.get(overId) : undefined
  const check: DropCheck = !dragging || !overId ? undefined : (allDrops?.get(overId) ?? singles[`${dragging.id}:${overId}`])

  // Until that answer is here, the shift under the pointer is checked on its own, right away.
  const known = check !== undefined
  useEffect(() => {
    if (!dragging || known || !isDropTarget(dragging, target)) return
    const key = `${dragging.id}:${target.id}`
    checker
      .mutateAsync({ versionId: data.id, data: { changes: swapChanges(dragging, target) } })
      .then((response) => setSingles((s) => ({ ...s, [key]: response.data as CheckOut })))
      .catch(() => setSingles((s) => ({ ...s, [key]: 'failed' })))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging, target, known])

  const onDragStart = (event: DragStartEvent) => {
    setMessage(null)
    setQuestion(null)
    setSingles({})
    setOverId(null)
    setDragging(byId.get(String(event.active.id)) ?? null)
  }
  const onDragOver = (event: DragOverEvent) => setOverId(event.over ? String(event.over.id) : null)
  const save = (changes: Change[], done: string, { force = false, removeClashes = false } = {}) =>
    change.mutate(
      { versionId: data.id, data: { changes, force, remove_clashes: removeClashes } },
      {
        onSuccess: () => {
          setMessage({ text: done, bad: false })
          setOverride(null)
          setQuestion(null)
          void queryClient.invalidateQueries()
        },
        onError: (error) => {
          setOverride(null)
          setQuestion(null)
          setMessage({ text: errorMessage(error, NETWORK_PROBLEM), bad: true })
        },
      },
    )
  const onDragEnd = (event: DragEndEvent) => {
    const from = byId.get(String(event.active.id))
    const to = event.over ? byId.get(String(event.over.id)) : undefined
    const known = to && overId === to.id && check && check !== 'failed' ? check : null
    setDragging(null)
    setOverId(null)
    if (!from || !to || from.id === to.id || from.employee_id === to.employee_id) return
    const changes = swapChanges(from, to)
    const done = to.employee_id ? `Zamienione: ${from.employee_name} i ${to.employee_name}.` : `Przeniesiono: ${from.employee_name}.`
    // Another shift at the same time: ask whether to take the person off it. A swap that breaks a hard rule is the
    // manager's call: ask once, then save it as an override.
    const decide = (result: CheckOut) => {
      if (result.clashes.length > 0) setQuestion({ changes, done, check: result })
      else if (result.ok) save(changes, done)
      else if (result.can_force) setOverride({ changes, problems: result.problems, done })
      else setMessage({ text: result.problems[0] ?? 'Tej zmiany nie można zapisać.', bad: true })
    }
    if (known) return decide(known)
    checker.mutate(
      { versionId: data.id, data: { changes } },
      {
        onSuccess: (response) => decide(response.data as CheckOut),
        onError: (error) => setMessage({ text: errorMessage(error, NETWORK_PROBLEM), bad: true }),
      },
    )
  }

  const addPlace = (date: string, column: GridColumn) => {
    if (!column.shiftTypeId) return
    setMessage(null)
    addSeat.mutate(
      { versionId: data.id, data: { date, shift_type_id: column.shiftTypeId, position_id: column.positionId } },
      {
        onSuccess: () => {
          setMessage({ text: 'Dodano miejsce. Wybierz je, żeby wpisać osobę.', bad: false })
          void queryClient.invalidateQueries()
        },
        onError: (error) => setMessage({ text: errorMessage(error, NETWORK_PROBLEM), bad: true }),
      },
    )
  }

  if (data.shifts.length === 0) {
    return (
      <EmptyState title="W tym grafiku nie ma zmian">
        <p className="m-0">Ustaw obsadę w ustawieniach lokalu i ułóż grafik jeszcze raz.</p>
      </EmptyState>
    )
  }

  return (
    <section className="grid gap-3" aria-label="Grafik">
      {editable && (
        <SelectField
          label="Pokaż, kiedy ta osoba chce i może pracować"
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          className="max-w-sm"
        >
          <option value="">Nikt nie jest wybrany</option>
          {data.employees.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
        </SelectField>
      )}
      <Legend person={!!personId} hours={data.shifts.some((s) => s.worked || s.hours_report)} />
      {message && (
        <p role="status" className={cn('m-0 rounded-sm px-3 py-2', message.bad ? 'bg-cannot-soft text-cannot' : 'bg-accent-soft')}>
          {message.text}
        </p>
      )}
      {question && (
        <ClashQuestion
          check={question.check}
          busy={change.isPending}
          onMove={(force) =>
            save(
              question.changes,
              `${question.done} ${question.check.clashes.length > 1 ? 'Tamte zmiany są teraz puste.' : 'Tamta zmiana jest teraz pusta.'}`,
              { force, removeClashes: true },
            )
          }
          onCancel={() => setQuestion(null)}
        />
      )}
      <DndContext
        sensors={sensors}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={() => {
          setDragging(null)
          setOverId(null)
        }}
      >
        <div className="rounded-md border border-line bg-surface">
          <div
            className="sticky top-0 z-10 hidden border-b-2 border-ink bg-surface lg:grid lg:grid-cols-(--grid-cols)"
            style={{ '--grid-cols': template } as React.CSSProperties}
          >
            <span className="px-3 py-2 text-sm font-semibold text-ink-muted">Dzień</span>
            {columns.map((c) => (
              <span key={c.key} className="grid px-2 py-2">
                <span className="font-semibold">
                  {c.shiftTypeName || 'Zmiana'} · {c.positionName}
                </span>
                <span className="text-sm text-ink-muted">
                  {c.start}–{c.end}
                </span>
              </span>
            ))}
          </div>
          {rows.map((row) => {
            const day = parseDate(row.date)
            const weekend = weekdayIndex(day) >= 5
            return (
              <div
                key={row.date}
                className={cn(
                  'grid gap-1 border-b border-grid p-2 lg:grid-cols-(--grid-cols) lg:gap-0 lg:p-0',
                  weekend && 'bg-paper',
                )}
                style={{ '--grid-cols': template } as React.CSSProperties}
              >
                <span className="px-1 pt-1 font-semibold lg:px-3 lg:py-2">
                  {weekdayShort(day)} {dayAndMonth(day)}
                </span>
                {columns.map((column) => {
                  const cell = row.cells[column.key] ?? []
                  return (
                    <div
                      key={column.key}
                      className={cn('grid min-w-0 content-start gap-1 px-1 lg:p-1.5', cell.length === 0 && 'hidden lg:grid')}
                    >
                      {cell.length > 0 && (
                        <span className="text-sm text-ink-muted lg:hidden">
                          {column.shiftTypeName || 'Zmiana'} · {column.positionName}
                        </span>
                      )}
                      {cell.length === 0 && editable && column.shiftTypeId && row.date >= data.today && (
                        <button
                          type="button"
                          disabled={addSeat.isPending}
                          onClick={() => addPlace(row.date, column)}
                          aria-label={`Dodaj miejsce: ${column.shiftTypeName} · ${column.positionName}, ${weekdayShort(day)} ${dayAndMonth(day)}`}
                          className="flex min-h-(--touch) w-full cursor-pointer items-center justify-center rounded-sm border-2 border-dashed border-line text-ink-muted hover:border-accent hover:text-accent disabled:opacity-50"
                        >
                          <Plus aria-hidden="true" size={18} />
                        </button>
                      )}
                      {cell.map((shift) => (
                        <ShiftChip
                          key={shift.id}
                          shift={shift}
                          column={column}
                          editable={editable}
                          dragging={dragging}
                          fit={fitByShift.get(shift.id)}
                          onOpen={() => setOpen(shift)}
                        />
                      ))}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
        <DragOverlay dropAnimation={null}>{dragging && <DragCard dragging={dragging} target={target} check={check} />}</DragOverlay>
      </DndContext>
      <ShiftSheet
        versionId={data.id}
        locationId={data.location_id}
        shift={open}
        editable={editable}
        published={data.status === 'published'}
        onClose={() => setOpen(null)}
      />
      <Sheet open={override !== null} onOpenChange={(o) => !o && setOverride(null)} title="Zapisać mimo to?">
        {override && (
          <div className="grid gap-4">
            <div className="grid gap-1 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
              {override.problems.map((problem) => (
                <span key={problem}>{problem}</span>
              ))}
            </div>
            <p className="m-0 text-sm text-ink-muted">
              Decyzja należy do Ciebie. Zmiana zostanie oznaczona i przypięta, więc ponowne układanie jej nie cofnie.
            </p>
            <Button wide disabled={change.isPending} onClick={() => save(override.changes, override.done, { force: true })}>
              {change.isPending ? 'Zapisuję…' : 'Zapisz mimo to'}
            </Button>
            <Button wide variant="secondary" onClick={() => setOverride(null)}>
              Anuluj
            </Button>
          </div>
        )}
      </Sheet>
    </section>
  )
}

/** The card under the pointer: who is dragged, what dropping here does and, as soon as it is known, the result. */
function DragCard({ dragging, target, check }: { dragging: VersionShiftOut; target?: VersionShiftOut; check: DropCheck }) {
  const words = dropWords(dragging, target, check)
  return (
    <div className="grid w-72 gap-1 rounded-sm border-2 border-accent bg-surface px-3 py-2 shadow-sheet">
      <span className="font-semibold">{dragging.employee_name}</span>
      <span className="text-sm text-ink-muted">{words.what}</span>
      <span role="status" className={cn('min-h-[1lh] text-sm', words.bad ? 'text-cannot' : 'text-ink-muted')}>
        {words.verdict}
      </span>
    </div>
  )
}

function ShiftChip({
  shift,
  column,
  editable,
  dragging,
  fit,
  onOpen,
}: {
  shift: VersionShiftOut
  column: { start: string; end: string }
  editable: boolean
  dragging: VersionShiftOut | null
  /** How the picked (or dragged) person fits this shift; absent when nobody is picked or it is not their position. */
  fit?: ShiftFitOut
  onOpen: () => void
}) {
  const canDrag = editable && !!shift.employee_id
  const draggable = useDraggable({ id: shift.id, disabled: !canDrag })
  const droppable = useDroppable({ id: shift.id, disabled: !editable })
  const hole = !shift.employee_id
  const otherHours = shift.start_time !== column.start || shift.end_time !== column.end
  const bad = shift.problems.length > 0
  const label = hole ? 'Bez obsady' : shift.employee_name
  const describe = [
    label,
    `${shift.start_time}–${shift.end_time}`,
    shift.pinned ? 'przypięta' : '',
    shift.manual ? 'zmieniona ręcznie' : '',
    shift.forced ? 'wpisana mimo przeszkód' : '',
    shift.worked ? `naprawdę ${shift.worked.start_time}–${shift.worked.end_time}` : '',
    shift.hours_report ? 'czeka zgłoszenie innych godzin' : '',
    bad ? 'łamie regułę' : '',
    fit ? FIT_WORDS[fit.fit] : '',
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div ref={droppable.setNodeRef} className="relative min-w-0">
      <button
        ref={draggable.setNodeRef}
        type="button"
        {...(canDrag ? { ...draggable.listeners, ...draggable.attributes } : {})}
        onClick={onOpen}
        aria-label={describe}
        className={cn(
          'flex min-h-(--touch) w-full cursor-pointer items-center gap-1.5 rounded-sm border-2 px-2 text-left text-base',
          fit
            ? cn(FIT_CLASS[fit.fit], hole && 'border-dashed font-semibold')
            : hole
              ? 'border-dashed border-cannot bg-cannot-soft font-semibold text-cannot'
              : bad
                ? 'border-cannot bg-surface'
                : 'border-line bg-surface hover:border-accent',
          shift.past && !fit && 'opacity-70',
          draggable.isDragging && 'opacity-40',
          droppable.isOver && dragging && 'border-accent ring-3 ring-accent-soft',
          canDrag && 'touch-none',
        )}
      >
        {fit ? (
          <span className="shrink-0" title={fit.reason}>
            <StateIcon state={fit.fit === 'can' ? 'neutral' : fit.fit} size={18} />
          </span>
        ) : (
          hole && <AlertTriangle aria-hidden="true" size={18} className="shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {otherHours && (
          <span className="shrink-0 text-sm text-ink-muted">
            {shift.start_time}–{shift.end_time}
          </span>
        )}
        {(shift.worked || shift.hours_report) && (
          <Clock
            aria-hidden="true"
            size={16}
            className={cn('shrink-0', shift.hours_report ? 'text-prefer-not' : 'text-ink-muted')}
          />
        )}
        {shift.forced && <ShieldAlert aria-hidden="true" size={16} className="shrink-0 text-prefer-not" />}
        {shift.manual && !shift.forced && <Hand aria-hidden="true" size={16} className="shrink-0 text-ink-muted" />}
        {shift.pinned && <Pin aria-hidden="true" size={16} className="shrink-0 text-accent" />}
      </button>
    </div>
  )
}

const FIT_CLASS: Record<ShiftFitOut['fit'], string> = {
  prefer: 'avail-prefer',
  can: 'avail-neutral',
  cannot: 'fit-cannot',
}

const FIT_WORDS: Record<ShiftFitOut['fit'], string> = {
  prefer: 'wybrana osoba chętnie',
  can: 'wybrana osoba może',
  cannot: 'wybrana osoba nie może',
}

function Legend({ person, hours = false }: { person: boolean; hours?: boolean }) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-sm text-ink-muted">
      {person && (
        <>
          <li className="avail-prefer flex items-center gap-1.5 rounded-sm border px-1.5 font-semibold">
            <StateIcon state="prefer" size={16} /> chętnie
          </li>
          <li className="avail-neutral flex items-center gap-1.5 rounded-sm border px-1.5 font-semibold">
            <StateIcon state="neutral" size={16} /> może
          </li>
          <li className="fit-cannot flex items-center gap-1.5 rounded-sm border px-1.5 font-semibold">
            <StateIcon state="cannot" size={16} /> nie może
          </li>
        </>
      )}
      <li className="flex items-center gap-1.5">
        <AlertTriangle aria-hidden="true" size={16} className="text-cannot" /> bez obsady
      </li>
      <li className="flex items-center gap-1.5">
        <Hand aria-hidden="true" size={16} /> zmienione ręcznie
      </li>
      <li className="flex items-center gap-1.5">
        <Pin aria-hidden="true" size={16} className="text-accent" /> przypięte
      </li>
      <li className="flex items-center gap-1.5">
        <ShieldAlert aria-hidden="true" size={16} className="text-prefer-not" /> wpisane mimo przeszkód
      </li>
      {hours && (
        <li className="flex items-center gap-1.5">
          <Clock aria-hidden="true" size={16} /> inne godziny (w karcie zmiany)
        </li>
      )}
    </ul>
  )
}

// ----------------------------------------------------------------------------------------------- below the grid

function PeopleHours({ data }: { data: VersionOut }) {
  return (
    <section className="grid content-start gap-2">
      <h2 className="m-0 text-lg font-extrabold">Godziny osób w tym grafiku</h2>
      <div className="overflow-x-auto rounded-md border border-line bg-surface">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b-2 border-ink">
              <th className="px-3 py-2">Osoba</th>
              <th className="px-3 py-2 text-right">Zmiany</th>
              <th className="px-3 py-2 text-right">Godziny</th>
              <th className="px-3 py-2 text-right">Cel / maks.</th>
            </tr>
          </thead>
          <tbody>
            {data.employees.map((e) => {
              const elsewhere = e.hours_elsewhere ?? 0
              const over = e.max_hours !== null && e.hours + elsewhere > e.max_hours
              return (
                <tr key={e.id} className="border-b border-grid">
                  <td className="px-3 py-2">
                    {e.name}
                    {e.home_location_name && (
                      <span className="block text-sm text-ink-muted">lokal główny: {e.home_location_name}</span>
                    )}
                    {!e.active && <span className="block text-sm text-ink-muted">wyłączony z grafiku</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{e.shifts}</td>
                  <td className={cn('px-3 py-2 text-right tabular-nums', over && 'font-semibold text-cannot')}>
                    {String(e.hours).replace('.', ',')}
                    {elsewhere > 0 && (
                      <span className="block text-sm font-normal text-ink-muted">
                        +{String(elsewhere).replace('.', ',')} w innych lokalach
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-ink-muted tabular-nums">
                    {e.target_hours ?? '–'} / {e.max_hours ?? '–'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="m-0 text-sm text-ink-muted">Cel i maksimum są na cały miesiąc.</p>
    </section>
  )
}

function RulesList({ data }: { data: VersionOut }) {
  if (data.rules.length === 0) return null
  return (
    <Section title="Jak grafik trzyma się zasad" collapsible status={<RulesStatus rules={data.rules} />}>
      <ul className="m-0 grid list-none gap-1 p-0">
        {data.rules.map((rule) => {
          const head = (
            <span className="flex flex-1 flex-wrap justify-between gap-x-2 py-1">
              <span className="font-semibold">
                {rule.label}
                {rule.hard && <span className="font-normal text-ink-muted"> (bez wyjątków)</span>}
              </span>
              <span className={cn(rule.broken > 0 ? 'text-prefer-not' : 'text-ink-muted')}>
                {rule.percent === null ? 'nic do oceny' : rule.hard ? 'spełniona' : percent(rule.percent)}
                {rule.broken > 0 && ` · złamana ${rule.broken}×`}
              </span>
            </span>
          )
          return (
            <li key={rule.code} className="rounded-sm border border-line bg-paper px-3">
              {rule.examples.length > 0 ? (
                <Disclosure summary={head}>
                  <ul className="mt-0 mb-2 grid gap-0.5 pl-5 text-sm text-ink-muted">
                    {rule.examples.map((example) => (
                      <li key={example}>{example}</li>
                    ))}
                  </ul>
                </Disclosure>
              ) : (
                // Nothing to unfold: the same line without a chevron, the label still in line with the others.
                <div className="flex min-h-(--touch) items-center gap-2">
                  <span aria-hidden="true" className="size-[1.2em] shrink-0" />
                  {head}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

/** The manager's own orders come first and stay in view: they matter more than any employee's request. */
function UnmetOrders({ data }: { data: VersionOut }) {
  const orders = data.unmet_requests.filter((r) => r.kind === 'instruction')
  if (orders.length === 0) return null
  return (
    <section className="grid gap-2">
      <h2 className="m-0 text-lg font-extrabold">Twoje polecenia, których nie udało się spełnić w całości</h2>
      <ul className="m-0 grid list-none gap-1 p-0">
        {orders.map((r, i) => (
          <li key={`o${i}`} className="rounded-sm border border-prefer-not bg-prefer-not-soft px-3 py-2">
            {r.text}
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * What the folded rules heading says. It claims "wszystkie spełnione" only when every rule is at 100 %:
 * a rule can be partly kept without a counted break (a soft hours target), and "nic do oceny" is not "spełniona".
 */
function RulesStatus({ rules }: { rules: VersionOut['rules'] }) {
  const broken = rules.filter((rule) => rule.broken > 0).length
  const partly = rules.filter((rule) => rule.broken === 0 && rule.percent !== null && rule.percent < 100).length
  const warn = [
    broken > 0 && countWords(broken, ['złamana', 'złamane', 'złamanych']),
    partly > 0 && countWords(partly, ['spełniona częściowo', 'spełnione częściowo', 'spełnionych częściowo']),
  ].filter(Boolean)
  if (warn.length > 0) return <span className="font-semibold text-prefer-not">{warn.join(' · ')}</span>
  const all = rules.every((rule) => rule.percent === 100)
  return <span className="text-ink-muted">{all ? 'wszystkie spełnione' : 'żadna nie jest złamana'}</span>
}

function UnmetRequests({ data }: { data: VersionOut }) {
  const scored = data.unmet_requests.filter((r) => r.kind !== 'unscored' && r.kind !== 'instruction')
  const yours = data.unmet_requests.filter((r) => r.kind === 'unscored')
  // The list is cut on the server; the count is not.
  const unmet = Math.max(data.unmet_request_count, scored.length)
  const shown = scored.slice(0, 12)
  return (
    <Section
      title="Niespełnione prośby"
      collapsible
      status={
        <>
          {unmet > 0 && (
            <span className="font-semibold text-prefer-not">{countWords(unmet, ['prośba', 'prośby', 'próśb'])}</span>
          )}
          {unmet > 0 && yours.length > 0 && <span className="text-ink-muted"> · </span>}
          {yours.length > 0 && <span className="text-ink-muted">{yours.length} do Twojej oceny</span>}
          {unmet === 0 && yours.length === 0 && <span className="text-ink-muted">wszystkie spełnione</span>}
        </>
      }
    >
      {unmet === 0 ? (
        <p className="m-0 text-ink-muted">Wszystkie prośby, które umiemy sprawdzić, są spełnione.</p>
      ) : (
        <ul className="m-0 grid list-none gap-1 p-0">
          {shown.map((r, i) => (
            <li key={`${r.employee_name}-${i}`} className="rounded-sm border border-line bg-paper px-3 py-2">
              <span className="font-semibold">{r.employee_name}: </span>
              {r.text}
            </li>
          ))}
        </ul>
      )}
      {unmet > shown.length && (
        <p className="m-0 text-sm text-ink-muted">I jeszcze {unmet - shown.length} innych.</p>
      )}
      {yours.length > 0 && (
        <>
          <h3 className="m-0 mt-2 text-base font-extrabold">Do Twojej oceny</h3>
          <p className="m-0 text-sm text-ink-muted">Tych próśb nie umiemy sprawdzić. Zobacz sam, czy są spełnione.</p>
          <ul className="m-0 grid list-none gap-1 p-0">
            {yours.map((r, i) => (
              <li key={`${r.employee_name}-u${i}`} className="rounded-sm border border-dashed border-line bg-paper px-3 py-2">
                <span className="font-semibold">{r.employee_name}: </span>
                {r.text}
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  )
}
