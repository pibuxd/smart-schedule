import { Check, Clock } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'

import {
  useCopyPreviousAvailability,
  useMyAvailability,
  useRepeatMyAvailability,
  useSaveMyAvailability,
  useSubmitMyAvailability,
} from '../../api/generated/availability/availability'
import type { MyAvailabilityOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import { addDays, dayAndMonth, dayTitle, parseDate, periodWords, toIsoDate, weekdayGenitive } from '../../lib/dates'
import { AvailabilityCalendar } from './AvailabilityCalendar'
import { DayHoursSheet } from './DayHoursSheet'
import {
  type AvailabilityState,
  changedDays,
  countStates,
  describeMark,
  hasHours,
  markOf,
  STATE_LABEL,
  STATES,
  type Marks,
  marksFromServer,
  sameMark,
  toDayIn,
} from './marks'
import { MoreOptionsSheet } from './MoreOptionsSheet'
import { RequestsSection } from './RequestsSection'
import { StateIcon } from './StateIcon'

type Tool = AvailabilityState | 'hours'
type SaveStatus = 'saved' | 'saving' | 'failed'

export function AvailabilityScreen({ companyId, readOnly }: { companyId: string; readOnly: boolean }) {
  // gcTime 0: the editor keeps its own copy while open, so a visit later always starts from the server.
  const query = useMyAvailability({ company_id: companyId }, { query: { gcTime: 0 } })

  if (query.isPending) return <Loading>Wczytuję kalendarz…</Loading>
  if (query.isError) {
    return (
      <ErrorState onRetry={() => void query.refetch()}>
        {errorMessage(query.error, 'Nie udało się wczytać kalendarza. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = query.data.data as MyAvailabilityOut
  if (!data.period) {
    return (
      <>
        <h1 className="m-0 text-xl font-extrabold">Kiedy mogę</h1>
        <EmptyState title="Na razie nie ma czego zaznaczać">
          <p className="m-0">
            Kierownik jeszcze nie poprosił o dyspozycje na kolejny okres. Gdy to zrobi, zaznaczysz tu, kiedy możesz
            pracować.
          </p>
        </EmptyState>
      </>
    )
  }
  return <AvailabilityEditor key={data.period.id} companyId={companyId} readOnly={readOnly} initial={data} />
}

function AvailabilityEditor({
  companyId,
  readOnly,
  initial,
}: {
  companyId: string
  readOnly: boolean
  initial: MyAvailabilityOut
}) {
  const period = initial.period!
  const editable = period.editable && !readOnly
  const [marks, setMarks] = useState<Marks>(() => marksFromServer(initial.days))
  const marksRef = useRef(marks)
  const [tool, setTool] = useState<Tool>('cannot')
  const [history, setHistory] = useState<Marks[]>([])
  const [openDay, setOpenDay] = useState<string | null>(null)
  const [moreOpen, setMoreOpen] = useState(false)
  const [moreError, setMoreError] = useState<string | null>(null)
  const [submittedAt, setSubmittedAt] = useState(initial.submitted_at)
  const [status, setStatus] = useState<SaveStatus>('saved')
  const [saveError, setSaveError] = useState<string | null>(null)
  const pending = useRef(0)
  const failed = useRef<Marks>({})
  const stroke = useRef<Marks | null>(null)

  const save = useSaveMyAvailability()
  const repeat = useRepeatMyAvailability()
  const copy = useCopyPreviousAvailability()
  const submit = useSubmitMyAvailability()
  const ids = { company_id: companyId, period_id: period.id }

  const apply = (changes: Marks) => {
    marksRef.current = { ...marksRef.current, ...changes }
    setMarks(marksRef.current)
  }

  const send = useCallback(
    (changes: Marks) => {
      const dates = Object.keys(changes)
      if (dates.length === 0) return
      pending.current += 1
      setStatus('saving')
      save.mutate(
        { data: { ...ids, days: dates.map((date) => toDayIn(date, changes[date])) } },
        {
          onSuccess: () => {
            for (const date of dates) delete failed.current[date]
            pending.current -= 1
            if (pending.current === 0) setStatus(Object.keys(failed.current).length ? 'failed' : 'saved')
          },
          onError: (error) => {
            for (const date of dates) failed.current[date] = markOf(marksRef.current, date)
            pending.current -= 1
            setSaveError(errorMessage(error, NETWORK_PROBLEM))
            setStatus('failed')
          },
        },
      )
    },
    // `ids` and `save.mutate` are stable for the life of the editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [companyId, period.id],
  )

  const record = (previous: Marks) => {
    if (Object.keys(previous).length) setHistory((h) => [...h, previous])
  }

  const paint = useCallback(
    (date: string) => {
      if (tool === 'hours') return
      stroke.current ??= {}
      if (date in stroke.current) return
      const before = markOf(marksRef.current, date)
      stroke.current[date] = before
      // A day that already has this state keeps its hours; a tap on it opens the day instead (see endStroke).
      if (before.state !== tool) apply({ [date]: { state: tool, from: null, to: null } })
    },
    [tool],
  )

  const endStroke = useCallback(() => {
    const touched = stroke.current ?? {}
    stroke.current = null
    const previous: Marks = {}
    const changes: Marks = {}
    for (const date of Object.keys(touched)) {
      if (!sameMark(touched[date], markOf(marksRef.current, date))) {
        previous[date] = touched[date]
        changes[date] = markOf(marksRef.current, date)
      }
    }
    const dates = Object.keys(touched)
    if (dates.length === 1 && Object.keys(changes).length === 0) {
      // Tapping a day that already shows the chosen state opens it: its hours can be seen and changed.
      setOpenDay(dates[0])
      return
    }
    record(previous)
    send(changes)
  }, [send])

  const undo = () => {
    const last = history[history.length - 1]
    if (!last) return
    setHistory((h) => h.slice(0, -1))
    apply(last)
    send(last)
  }

  const replaceAll = (response: MyAvailabilityOut) => {
    const next = marksFromServer(response.days)
    record(changedDays(marksRef.current, next))
    marksRef.current = next
    setMarks(next)
    setMoreOpen(false)
    setMoreError(null)
  }

  const dates: string[] = []
  for (let d = parseDate(period.start); d <= parseDate(period.end); d = addDays(d, 1)) dates.push(toIsoDate(d))
  const counts = countStates(marks, dates)
  const deadline = parseDate(period.deadline)
  const pastDeadline = toIsoDate(new Date()) > period.deadline

  return (
    <div className="grid gap-4">
      <div className="flex items-start justify-between gap-3">
        <h1 className="m-0 text-xl font-extrabold">Kiedy mogę {periodWords(period.start, period.end)}</h1>
        {editable && <SaveIndicator status={status} />}
      </div>

      <p className="m-0 rounded-md bg-accent-soft px-3.5 py-2.5 text-sm">
        {readOnly ? (
          'Twoja firma ma teraz wstrzymany dostęp do aplikacji, więc nie da się nic zaznaczać. Grafik nadal widać.'
        ) : !period.editable ? (
          'Kierownik już układa grafik na ten okres. Jeśli coś się zmieniło, powiedz mu o tym.'
        ) : pastDeadline ? (
          <>
            Termin minął {dayAndMonth(deadline)}, ale kierownik jeszcze nie układa grafiku, więc możesz poprawiać.
          </>
        ) : (
          <>
            Zaznacz do{' '}
            <b className="text-base">
              {weekdayGenitive(deadline)} {dayAndMonth(deadline)}
            </b>
            . Potem kierownik układa grafik.
          </>
        )}
      </p>

      {status === 'failed' && (
        <div className="grid gap-2">
          <InlineError>{saveError ?? NETWORK_PROBLEM}</InlineError>
          <Button variant="secondary" size="normal" onClick={() => send({ ...failed.current })}>
            Zapisz jeszcze raz
          </Button>
        </div>
      )}

      <AvailabilityCalendar
        start={period.start}
        end={period.end}
        marks={marks}
        disabled={!editable}
        onPaint={paint}
        onStroke={endStroke}
        onOpenDay={tool === 'hours' ? setOpenDay : undefined}
      />

      <DaysWithHours marks={marks} dates={dates} editable={editable} onOpen={setOpenDay} />

      <p className="m-0 flex flex-wrap gap-x-3.5 gap-y-1 text-sm text-ink-muted" aria-live="polite">
        <span>
          Chętnie: <b className="text-ink tabular-nums">{counts.prefer}</b>
        </span>
        <span>
          Wolę nie: <b className="text-ink tabular-nums">{counts.prefer_not}</b>
        </span>
        <span>
          Nie mogę: <b className="text-ink tabular-nums">{counts.cannot}</b>
        </span>
      </p>

      {editable && (
        <>
          <ToolBar tool={tool} onChange={setTool} />
          <button
            type="button"
            aria-pressed={tool === 'hours'}
            onClick={() => setTool(tool === 'hours' ? 'cannot' : 'hours')}
            className={cn(
              'flex min-h-(--touch-main) cursor-pointer items-center gap-2.5 rounded-md border-2 border-line bg-surface px-3 text-left font-semibold',
              tool === 'hours' && 'border-accent bg-accent-soft ring-3 ring-accent-soft',
            )}
          >
            <Clock aria-hidden="true" size={26} className="flex-none text-accent" />
            <span>
              Godziny dnia
              <span className="block text-sm font-normal text-ink-muted">
                {tool === 'hours' ? 'Stuknij dzień w kalendarzu. Stuknij tu, żeby wrócić.' : 'Gdy możesz tylko w części dnia'}
              </span>
            </span>
          </button>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="secondary" disabled={history.length === 0} onClick={undo}>
              Cofnij
            </Button>
            <Button variant="secondary" onClick={() => setMoreOpen(true)}>
              Więcej opcji
            </Button>
          </div>
          {submittedAt ? (
            <p className="m-0 flex items-start gap-2 rounded-md border-2 border-prefer bg-prefer-soft px-3.5 py-3 text-prefer">
              <Check aria-hidden="true" size={22} className="mt-0.5 flex-none" />
              <span>
                Wysłane do kierownika {dayAndMonth(new Date(submittedAt))}. Do terminu możesz jeszcze coś zmienić,
                zapisuje się samo.
              </span>
            </p>
          ) : (
            <div className="grid gap-2">
              <Button
                wide
                disabled={submit.isPending}
                onClick={() =>
                  submit.mutate(
                    { data: ids },
                    { onSuccess: (r) => setSubmittedAt((r.data as MyAvailabilityOut).submitted_at) },
                  )
                }
              >
                Gotowe, wysyłam kierownikowi
              </Button>
              <p className="m-0 text-sm text-ink-muted">
                Każdy dzień zapisuje się od razu. Dni bez zaznaczenia liczą się jako „obojętnie”.
              </p>
              {submit.isError && <InlineError>{errorMessage(submit.error, NETWORK_PROBLEM)}</InlineError>}
            </div>
          )}
        </>
      )}

      <RequestsSection companyId={companyId} periodId={period.id} editable={editable} />

      {openDay && (
        <DayHoursSheet
          date={openDay}
          mark={markOf(marks, openDay)}
          onClose={() => setOpenDay(null)}
          onSave={(mark) => {
            const before = markOf(marksRef.current, openDay)
            if (!sameMark(before, mark)) {
              record({ [openDay]: before })
              apply({ [openDay]: mark })
              send({ [openDay]: mark })
            }
            setOpenDay(null)
          }}
        />
      )}
      <MoreOptionsSheet
        open={moreOpen}
        onOpenChange={(open) => {
          setMoreOpen(open)
          setMoreError(null)
        }}
        periodEnd={period.end}
        marks={marks}
        dates={dates}
        busy={repeat.isPending || copy.isPending}
        error={moreError}
        onRepeat={(weekdays, state, until) =>
          repeat.mutate(
            { data: { ...ids, weekdays, state, repeat_until: until } },
            {
              onSuccess: (r) => replaceAll(r.data as MyAvailabilityOut),
              onError: (e) => setMoreError(errorMessage(e, NETWORK_PROBLEM)),
            },
          )
        }
        onCopy={() =>
          copy.mutate(
            { data: ids },
            {
              onSuccess: (r) => replaceAll(r.data as MyAvailabilityOut),
              onError: (e) => setMoreError(errorMessage(e, NETWORK_PROBLEM)),
            },
          )
        }
      />
    </div>
  )
}

function SaveIndicator({ status }: { status: SaveStatus }) {
  if (status === 'saving') {
    return (
      <span role="status" className="pt-1 text-sm whitespace-nowrap text-ink-muted">
        Zapisuję…
      </span>
    )
  }
  if (status === 'failed') {
    return <span className="pt-1 text-sm font-semibold whitespace-nowrap text-cannot">Nie zapisano</span>
  }
  return (
    <span role="status" className="flex items-center gap-1 pt-1 text-sm font-semibold whitespace-nowrap text-prefer">
      <Check aria-hidden="true" size={16} />
      Zapisane
    </span>
  )
}

/**
 * What a tap or a drag marks. Stays at the bottom of the screen while scrolling,
 * so the chosen state is always in sight.
 */
function ToolBar({ tool, onChange }: { tool: Tool; onChange: (tool: Tool) => void }) {
  return (
    <div className="sticky bottom-[calc(65px+env(safe-area-inset-bottom))] z-20 -mx-4 border-t border-line bg-paper px-4 pt-2 pb-2.5 md:bottom-0">
      <p className="m-0 mb-1.5 text-sm font-semibold" id="tool-label">
        {tool === 'hours' ? 'Stuknij dzień, żeby ustawić godziny.' : 'Zaznaczam dni jako:'}
      </p>
      <div role="group" aria-labelledby="tool-label" className="grid grid-cols-4 gap-1.5">
        {STATES.map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={tool === t}
            onClick={() => onChange(t)}
            className={cn(
              'grid min-h-16 min-w-0 cursor-pointer place-items-center gap-0.5 rounded-md border-2 border-line bg-surface px-0.5 py-1.5 text-sm font-semibold',
              tool === t && 'border-accent bg-accent-soft ring-3 ring-accent-soft',
            )}
          >
            <i className={cn(`avail-${t}`, 'grid size-7 place-items-center rounded-sm border-2')}>
              <StateIcon state={t} size={16} />
            </i>
            {STATE_LABEL[t]}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Days marked with hours, written out, so the hours can be read and changed without hunting in the grid. */
function DaysWithHours({
  marks,
  dates,
  editable,
  onOpen,
}: {
  marks: Marks
  dates: string[]
  editable: boolean
  onOpen: (date: string) => void
}) {
  const withHours = dates.filter((date) => hasHours(markOf(marks, date)))
  if (withHours.length === 0) return null
  return (
    <section aria-labelledby="hours-days" className="grid gap-2">
      <h2 id="hours-days" className="m-0 text-base font-extrabold">
        Dni z godzinami
      </h2>
      <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
        {withHours.map((date) => (
          <li key={date} className="flex items-center justify-between gap-3 border-t border-grid px-3.5 py-1.5 first:border-t-0">
            <span className="min-w-0">
              <span className="font-semibold">{dayTitle(parseDate(date))}</span>
              <span className="block text-sm text-ink-muted">{describeMark(markOf(marks, date))}</span>
            </span>
            {editable && (
              <Button variant="quiet" size="normal" className="px-2" onClick={() => onOpen(date)}>
                Zmień
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
