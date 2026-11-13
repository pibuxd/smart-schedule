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
import { AlertTriangle, CalendarPlus, Hand, Pin, Send, SquarePen } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'

import type { CheckOut, PeriodOut, ScoresOut, VersionOut, VersionShiftOut } from '../../api/generated/model'
import {
  useChangeAssignments,
  useCheckScheduleChanges,
  useLocationPeriods,
  usePinShift,
  usePublishSchedule,
  useScheduleVersion,
  useStartCorrecting,
} from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { SelectField, Tag } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import { dayAndMonth, parseDate, weekdayIndex, weekdayShort } from '../../lib/dates'
import { StateIcon } from '../availability/StateIcon'
import { ArrangeButton, RunProgress } from './ArrangeSchedule'
import { useManager } from './ManagerContext'
import { pickPeriod } from './periods'
import { buildGrid, percent, swapChanges } from './schedule-grid'
import { ShiftSheet } from './ShiftSheet'
import { daysUntil, PERIOD_STATUS, periodTitle, shifts as shiftsWord } from './words'

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
        <p className="m-0">Najpierw ustal daty okresu i termin dyspozycji na karcie „Dyspozycje”.</p>
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
              Bez dyspozycji: {period.missing_availability}. Grafik układasz sam, gdy uznasz, że czas.
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
              Ułożenie od nowa zostawia przypięte zmiany i dni, które minęły; resztę układa od początku.
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
              Gdy minie termin dyspozycji albo wszyscy je wpiszą, naciśnij „Ułóż grafik”. Zobaczysz szkic, który możesz
              poprawić, zanim pokażesz go pracownikom.
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
      <Scores scores={data.scores} />
      {data.hard_problems.length > 0 && (
        <div role="alert" className="grid gap-1 rounded-md border border-cannot bg-cannot-soft p-3 text-cannot">
          <span className="font-semibold">Ten grafik łamie reguły, więc nie można go opublikować:</span>
          {data.hard_problems.map((p) => (
            <span key={p}>{p}</span>
          ))}
        </div>
      )}
      {data.editable && <UnpinnedChanges data={data} />}
      <ScheduleGrid data={data} />
      <div className="grid gap-6 lg:grid-cols-2">
        <PeopleHours data={data} />
        <div className="grid content-start gap-6">
          <RulesList data={data} />
          <UnmetRequests data={data} />
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
        <span className="text-sm text-ink-muted">
          {data.status === 'draft'
            ? 'Pracownicy jeszcze tego nie widzą. Kliknij zmianę, żeby zobaczyć, kto może ją wziąć; przeciągnij osobę na inną zmianę, żeby je zamienić.'
            : data.status === 'published'
              ? 'Ten grafik widzą pracownicy w „Mój grafik”.'
              : 'Starsza wersja, tylko do podglądu.'}
        </span>
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
        {data.editable && (
          <Button size="normal" onClick={() => setPublishing(true)} disabled={data.scores.hard_violations > 0}>
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

/** Manual changes are dropped when the schedule is arranged again, unless pinned: say so and pin them in one go. */
function UnpinnedChanges({ data }: { data: VersionOut }) {
  const pin = usePinShift()
  const queryClient = useQueryClient()
  const [pinning, setPinning] = useState(false)
  const unpinned = data.shifts.filter((s) => s.manual && !s.pinned && s.employee_id && !s.past)
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
        Ręczne poprawki bez przypięcia: {unpinned.length}. Jeśli ułożysz grafik od nowa, znikną. Przypięte zostaną na
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
          Pracownicy zobaczą swoje zmiany w „Mój grafik” od razu po publikacji.
          {data.period.published_version_id ? ' Poprzednia wersja zostanie w historii.' : ''}
        </p>
        {data.changed_people.length > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
            Ta poprawka zmienia zmiany tych osób: {data.changed_people.join(', ')}. Daj im znać, bo mogły już
            zaplanować czas według poprzedniej wersji.
          </p>
        )}
        <p className="m-0 text-sm text-ink-muted">
          Powiadomienia w aplikacji pojawią się w jednej z następnych wersji. Na razie powiedz pracownikom, że grafik
          jest gotowy.
        </p>
        {holes > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-cannot bg-cannot-soft px-3 py-2">
            Grafik jest niekompletny: {shiftsWord(holes)} bez obsady. Możesz go opublikować i obsadzić te zmiany później.
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
          'grid content-start gap-1 rounded-md border-2 p-4',
          incomplete ? 'border-cannot bg-cannot-soft text-cannot' : 'border-line bg-surface',
        )}
      >
        <span className="text-sm font-semibold">Zmiany bez obsady</span>
        <span className="text-2xl font-extrabold">
          {scores.holes} <span className="text-base font-semibold">z {scores.slots}</span>
        </span>
        <span className="text-sm">{incomplete ? 'Grafik niekompletny: brakuje ludzi.' : 'Wszystkie zmiany obsadzone.'}</span>
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
    <div className="grid content-start gap-1 rounded-md border-2 border-line bg-surface p-4">
      <span className="text-sm font-semibold text-ink-muted">{label}</span>
      <span className={cn('text-2xl font-extrabold', muted ? 'text-ink-muted' : 'text-ink')}>{percent(value)}</span>
      {note && <span className="text-sm text-ink-muted">{note}</span>}
    </div>
  )
}

// ----------------------------------------------------------------------------------------------- the grid

type DragCheck = { overId: string; result: CheckOut | null; failed: boolean }

function ScheduleGrid({ data }: { data: VersionOut }) {
  const { columns, rows } = useMemo(() => buildGrid(data.shifts, data.period.start, data.period.end), [data])
  const byId = useMemo(() => new Map(data.shifts.map((s) => [s.id, s])), [data])
  const [open, setOpen] = useState<VersionShiftOut | null>(null)
  const [dragging, setDragging] = useState<VersionShiftOut | null>(null)
  const [check, setCheck] = useState<DragCheck | null>(null)
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)
  const checker = useCheckScheduleChanges()
  const change = useChangeAssignments()
  const queryClient = useQueryClient()
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))
  const editable = data.editable
  const template = `120px repeat(${columns.length}, minmax(0, 1fr))`

  // Live check while dragging: what the swap would break, before it is dropped.
  const overId = check?.overId
  useEffect(() => {
    if (!dragging || !overId || overId === dragging.id) return
    const target = byId.get(overId)
    if (!target) return
    const timer = window.setTimeout(() => {
      checker.mutate(
        { versionId: data.id, data: { changes: swapChanges(dragging, target) } },
        {
          onSuccess: (response) =>
            setCheck((c) => (c?.overId === overId ? { overId, result: response.data as CheckOut, failed: false } : c)),
          onError: () => setCheck((c) => (c?.overId === overId ? { overId, result: null, failed: true } : c)),
        },
      )
    }, 150)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging, overId])

  const onDragStart = (event: DragStartEvent) => {
    setMessage(null)
    setDragging(byId.get(String(event.active.id)) ?? null)
  }
  const onDragOver = (event: DragOverEvent) => {
    const id = event.over ? String(event.over.id) : null
    setCheck(id ? { overId: id, result: null, failed: false } : null)
  }
  const onDragEnd = (event: DragEndEvent) => {
    const from = byId.get(String(event.active.id))
    const to = event.over ? byId.get(String(event.over.id)) : undefined
    setDragging(null)
    setCheck(null)
    if (!from || !to || from.id === to.id || from.employee_id === to.employee_id) return
    change.mutate(
      { versionId: data.id, data: { changes: swapChanges(from, to) } },
      {
        onSuccess: () => {
          setMessage({
            text: to.employee_id ? `Zamienione: ${from.employee_name} i ${to.employee_name}.` : `Przeniesiono: ${from.employee_name}.`,
            bad: false,
          })
          void queryClient.invalidateQueries()
        },
        onError: (error) => setMessage({ text: errorMessage(error, NETWORK_PROBLEM), bad: true }),
      },
    )
  }

  if (data.shifts.length === 0) {
    return (
      <EmptyState title="W tym grafiku nie ma zmian">
        <p className="m-0">Ustaw obsadę w ustawieniach lokalu i ułóż grafik ponownie.</p>
      </EmptyState>
    )
  }

  return (
    <section className="grid gap-3" aria-label="Grafik">
      <Legend />
      {message && (
        <p role="status" className={cn('m-0 rounded-sm px-3 py-2', message.bad ? 'bg-cannot-soft text-cannot' : 'bg-accent-soft')}>
          {message.text}
        </p>
      )}
      <DndContext
        sensors={sensors}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={() => {
          setDragging(null)
          setCheck(null)
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
                      {cell.map((shift) => (
                        <ShiftChip
                          key={shift.id}
                          shift={shift}
                          column={column}
                          editable={editable && !shift.past}
                          dragging={dragging}
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
        <DragOverlay dropAnimation={null}>
          {dragging && (
            <div className="grid w-72 gap-1 rounded-sm border-2 border-accent bg-surface px-3 py-2 shadow-sheet">
              <span className="font-semibold">{dragging.employee_name}</span>
              <span role="status" className={cn('text-sm', dropWords(check).bad ? 'text-cannot' : 'text-ink-muted')}>
                {dropWords(check).text}
              </span>
            </div>
          )}
        </DragOverlay>
      </DndContext>
      <ShiftSheet versionId={data.id} shift={open} editable={editable} onClose={() => setOpen(null)} />
    </section>
  )
}

/** What dropping here would do, while the person is being dragged. */
function dropWords(check: DragCheck | null): { text: string; bad: boolean } {
  if (!check) return { text: 'Upuść na innej zmianie, żeby zamienić osoby.', bad: false }
  if (check.failed) return { text: 'Nie udało się sprawdzić tej zamiany.', bad: true }
  if (!check.result) return { text: 'Sprawdzam…', bad: false }
  if (!check.result.ok) return { text: check.result.problems[0], bad: true }
  const after = check.result.after
  return { text: `Można. Zasady ${percent(after.manager_rules)}, prośby ${percent(after.employee_requests)}.`, bad: false }
}

function ShiftChip({
  shift,
  column,
  editable,
  dragging,
  onOpen,
}: {
  shift: VersionShiftOut
  column: { start: string; end: string }
  editable: boolean
  dragging: VersionShiftOut | null
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
    shift.wish === 'prefer_not' ? 'ta osoba woli nie pracować tego dnia' : '',
    bad ? 'łamie regułę' : '',
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
          hole
            ? 'border-dashed border-cannot bg-cannot-soft font-semibold text-cannot'
            : bad
              ? 'border-cannot bg-surface'
              : 'border-line bg-surface hover:border-accent',
          shift.past && 'opacity-70',
          draggable.isDragging && 'opacity-40',
          droppable.isOver && dragging && 'border-accent ring-3 ring-accent-soft',
          canDrag && 'touch-none',
        )}
      >
        {hole && <AlertTriangle aria-hidden="true" size={18} className="shrink-0" />}
        {!hole && shift.wish === 'prefer_not' && (
          <span className="avail-prefer_not inline-flex shrink-0 rounded-sm border" title="woli nie">
            <StateIcon state="prefer_not" size={16} />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {otherHours && (
          <span className="shrink-0 text-sm text-ink-muted">
            {shift.start_time}–{shift.end_time}
          </span>
        )}
        {shift.manual && <Hand aria-hidden="true" size={16} className="shrink-0 text-ink-muted" />}
        {shift.pinned && <Pin aria-hidden="true" size={16} className="shrink-0 text-accent" />}
      </button>
    </div>
  )
}

function Legend() {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-sm text-ink-muted">
      <li className="flex items-center gap-1.5">
        <AlertTriangle aria-hidden="true" size={16} className="text-cannot" /> bez obsady
      </li>
      <li className="flex items-center gap-1.5">
        <span className="avail-prefer_not inline-flex rounded-sm border">
          <StateIcon state="prefer_not" size={14} />
        </span>
        woli nie pracować tego dnia
      </li>
      <li className="flex items-center gap-1.5">
        <Hand aria-hidden="true" size={16} /> zmienione ręcznie
      </li>
      <li className="flex items-center gap-1.5">
        <Pin aria-hidden="true" size={16} className="text-accent" /> przypięte
      </li>
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
              const over = e.max_hours !== null && e.hours > e.max_hours
              return (
                <tr key={e.id} className="border-b border-grid">
                  <td className="px-3 py-2">
                    {e.name}
                    {!e.active && <span className="block text-sm text-ink-muted">wyłączony z grafiku</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{e.shifts}</td>
                  <td className={cn('px-3 py-2 text-right tabular-nums', over && 'font-semibold text-cannot')}>
                    {String(e.hours).replace('.', ',')}
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
    <section className="grid gap-2">
      <h2 className="m-0 text-lg font-extrabold">Jak grafik trzyma się zasad</h2>
      <ul className="m-0 grid list-none gap-1 p-0">
        {data.rules.map((rule) => (
          <li key={rule.code} className="rounded-sm border border-line bg-surface px-3 py-2">
            <details>
              <summary className={cn('flex cursor-pointer flex-wrap justify-between gap-2', rule.broken === 0 && 'cursor-default')}>
                <span className="font-semibold">
                  {rule.label}
                  {rule.hard && <span className="font-normal text-ink-muted"> (bez wyjątków)</span>}
                </span>
                <span className={cn(rule.broken > 0 ? 'text-prefer-not' : 'text-ink-muted')}>
                  {rule.percent === null ? 'nic do oceny' : rule.hard ? 'spełniona' : percent(rule.percent)}
                  {rule.broken > 0 && ` · złamana ${rule.broken}×`}
                </span>
              </summary>
              {rule.examples.length > 0 && (
                <ul className="mt-1 mb-0 grid gap-0.5 pl-5 text-sm text-ink-muted">
                  {rule.examples.map((example) => (
                    <li key={example}>{example}</li>
                  ))}
                </ul>
              )}
            </details>
          </li>
        ))}
      </ul>
    </section>
  )
}

function UnmetRequests({ data }: { data: VersionOut }) {
  const scored = data.unmet_requests.filter((r) => r.kind !== 'unscored')
  const yours = data.unmet_requests.filter((r) => r.kind === 'unscored')
  return (
    <section className="grid gap-2">
      <h2 className="m-0 text-lg font-extrabold">Niespełnione prośby</h2>
      {scored.length === 0 ? (
        <p className="m-0 text-ink-muted">Grafik spełnia wszystkie prośby, które da się sprawdzić.</p>
      ) : (
        <ul className="m-0 grid list-none gap-1 p-0">
          {scored.slice(0, 12).map((r, i) => (
            <li key={`${r.employee_name}-${i}`} className="rounded-sm border border-line bg-surface px-3 py-2">
              <span className="font-semibold">{r.employee_name}: </span>
              {r.text}
            </li>
          ))}
        </ul>
      )}
      {scored.length > 12 && <p className="m-0 text-sm text-ink-muted">I jeszcze {scored.length - 12} innych.</p>}
      {yours.length > 0 && (
        <>
          <h3 className="m-0 mt-2 text-base font-extrabold">Do Twojej oceny</h3>
          <p className="m-0 text-sm text-ink-muted">Tych próśb grafik nie umie sprawdzić sam; zobacz, czy są spełnione.</p>
          <ul className="m-0 grid list-none gap-1 p-0">
            {yours.map((r, i) => (
              <li key={`${r.employee_name}-u${i}`} className="rounded-sm border border-dashed border-line bg-surface px-3 py-2">
                <span className="font-semibold">{r.employee_name}: </span>
                {r.text}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
