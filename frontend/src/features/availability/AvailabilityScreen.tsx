import { Check, ChevronLeft, ChevronRight, Clock } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'

import {
  useMyAvailability,
  useMyCalendar,
  useSaveMyCalendar,
  useSubmitMyAvailability,
} from '../../api/generated/availability/availability'
import type { AvailabilityPeriodOut, MyAvailabilityOut, MyCalendarOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import {
  addDays,
  dayAndMonth,
  dayTitle,
  monthName,
  parseDate,
  periodWords,
  toIsoDate,
  weekdayGenitive,
} from '../../lib/dates'
import { AvailabilityCalendar } from './AvailabilityCalendar'
import { DayHoursSheet } from './DayHoursSheet'
import {
  type AvailabilityState,
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
import { RequestsSection } from './RequestsSection'
import { StateIcon } from './StateIcon'

type Tool = AvailabilityState | 'hours'
type SaveStatus = 'saved' | 'saving' | 'failed'

/** How many months ahead of the current one the calendar reaches. */
const MONTHS_AHEAD = 3

const monthOf = (iso: string) => iso.slice(0, 7)

function monthBounds(month: string): { start: string; end: string } {
  const first = parseDate(`${month}-01`)
  return { start: toIsoDate(first), end: toIsoDate(new Date(first.getFullYear(), first.getMonth() + 1, 0)) }
}

function addMonths(month: string, count: number): string {
  const first = parseDate(`${month}-01`)
  return monthOf(toIsoDate(new Date(first.getFullYear(), first.getMonth() + count, 1)))
}

/**
 * "Kiedy mogę" is always open: the employee marks days month by month, also before the manager asks.
 * When the manager has asked for a period, the screen opens on it and shows the deadline and "Wyślij kierownikowi".
 */
export function AvailabilityScreen({
  companyId,
  readOnly,
  today = new Date(),
}: {
  companyId: string
  readOnly: boolean
  today?: Date
}) {
  // gcTime 0: the editor keeps its own copy while open, so a visit later always starts from the server.
  const query = useMyAvailability({ company_id: companyId }, { query: { gcTime: 0 } })
  const [chosen, setChosen] = useState<string | null>(null)
  const [submittedNow, setSubmittedNow] = useState<string | null>(null)

  if (query.isPending) return <Loading>Wczytuję kalendarz…</Loading>
  if (query.isError) {
    return (
      <ErrorState onRetry={() => void query.refetch()}>
        {errorMessage(query.error, 'Nie udało się wczytać kalendarza. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = query.data.data as MyAvailabilityOut
  const period = data.period ?? null
  const thisMonth = monthOf(toIsoDate(today))
  const requested = period ? monthOf(period.start < toIsoDate(today) ? toIsoDate(today) : period.start) : null
  const lastMonth = [addMonths(thisMonth, MONTHS_AHEAD), period ? monthOf(period.end) : thisMonth].sort().pop()!
  const month = chosen ?? requested ?? thisMonth

  return (
    <div className="grid gap-4">
      <h1 className="m-0 text-xl font-extrabold">Kiedy mogę pracować</h1>
      <PeriodNote period={period} readOnly={readOnly} today={today} />
      <MonthPager
        month={month}
        onChange={setChosen}
        canGoBack={month > thisMonth}
        canGoForward={month < lastMonth}
      />
      <MonthEditor
        key={month}
        companyId={companyId}
        month={month}
        readOnly={readOnly}
        period={period}
        assistantReads={data.assistant_reads ?? false}
        submittedAt={submittedNow ?? data.submitted_at}
        onSubmitted={setSubmittedNow}
      />
    </div>
  )
}

/** What the manager is waiting for, if anything. */
function PeriodNote({ period, readOnly, today }: { period: AvailabilityPeriodOut | null; readOnly: boolean; today: Date }) {
  let text: React.ReactNode
  if (readOnly) {
    text = 'Firma ma teraz wstrzymany dostęp do aplikacji, więc nic nie zaznaczysz. Grafik nadal widać.'
  } else if (!period) {
    text =
      'Zaznacz, kiedy możesz pracować w kolejnych miesiącach. Kierownik zobaczy to, gdy będzie układać grafik.'
  } else {
    const deadline = parseDate(period.deadline)
    const when = periodWords(period.start, period.end)
    text =
      toIsoDate(today) > period.deadline ? (
        <>
          Zaznacz, kiedy możesz pracować {when}. Termin minął {dayAndMonth(deadline)}, ale kierownik nie ułożył
          jeszcze grafiku, więc nadal możesz zmieniać.
        </>
      ) : (
        <>
          Zaznacz, kiedy możesz pracować {when}. Masz czas do{' '}
          <b className="text-base">
            {weekdayGenitive(deadline)} {dayAndMonth(deadline)}
          </b>
          . Potem kierownik ułoży grafik.
        </>
      )
  }
  return <p className="m-0 rounded-md bg-accent-soft px-3.5 py-2.5 text-sm">{text}</p>
}

function MonthPager({
  month,
  onChange,
  canGoBack,
  canGoForward,
}: {
  month: string
  onChange: (month: string) => void
  canGoBack: boolean
  canGoForward: boolean
}) {
  const arrow =
    'grid size-(--touch) flex-none cursor-pointer place-items-center rounded-md border-2 border-line bg-surface text-accent disabled:cursor-default disabled:opacity-40'
  return (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button"
        className={arrow}
        aria-label="Poprzedni miesiąc"
        disabled={!canGoBack}
        onClick={() => onChange(addMonths(month, -1))}
      >
        <ChevronLeft aria-hidden="true" size={26} />
      </button>
      <h2 className="m-0 text-lg font-extrabold" aria-live="polite">
        {monthName(month)}
      </h2>
      <button
        type="button"
        className={arrow}
        aria-label="Następny miesiąc"
        disabled={!canGoForward}
        onClick={() => onChange(addMonths(month, 1))}
      >
        <ChevronRight aria-hidden="true" size={26} />
      </button>
    </div>
  )
}

function MonthEditor(props: {
  companyId: string
  month: string
  readOnly: boolean
  period: AvailabilityPeriodOut | null
  assistantReads: boolean
  submittedAt: string | null | undefined
  onSubmitted: (at: string | null) => void
}) {
  const { start, end } = monthBounds(props.month)
  const calendar = useMyCalendar({ company_id: props.companyId, start, end }, { query: { gcTime: 0 } })
  if (calendar.isPending) return <Loading>Wczytuję kalendarz…</Loading>
  if (calendar.isError) {
    return (
      <ErrorState onRetry={() => void calendar.refetch()}>
        {errorMessage(calendar.error, 'Nie udało się wczytać kalendarza. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  return <AvailabilityEditor {...props} initial={calendar.data.data as MyCalendarOut} />
}

function AvailabilityEditor({
  companyId,
  readOnly,
  period,
  assistantReads,
  submittedAt,
  onSubmitted,
  initial,
}: {
  companyId: string
  readOnly: boolean
  period: AvailabilityPeriodOut | null
  assistantReads: boolean
  submittedAt: string | null | undefined
  onSubmitted: (at: string | null) => void
  initial: MyCalendarOut
}) {
  const dates: string[] = []
  for (let d = parseDate(initial.start); d <= parseDate(initial.end); d = addDays(d, 1)) dates.push(toIsoDate(d))
  const [locked] = useState(() => new Set(initial.locked))
  const editable = !readOnly && locked.size < dates.length
  const [marks, setMarks] = useState<Marks>(() => marksFromServer(initial.days))
  const marksRef = useRef(marks)
  const [tool, setTool] = useState<Tool>('cannot')
  const [openDay, setOpenDay] = useState<string | null>(null)
  const [status, setStatus] = useState<SaveStatus>('saved')
  const [saveError, setSaveError] = useState<string | null>(null)
  const pending = useRef(0)
  const failed = useRef<Marks>({})
  const stroke = useRef<Marks | null>(null)

  const save = useSaveMyCalendar()
  const submit = useSubmitMyAvailability()

  const apply = (changes: Marks) => {
    marksRef.current = { ...marksRef.current, ...changes }
    setMarks(marksRef.current)
  }

  const send = useCallback(
    (changes: Marks) => {
      const changed = Object.keys(changes)
      if (changed.length === 0) return
      pending.current += 1
      setStatus('saving')
      save.mutate(
        { data: { company_id: companyId, days: changed.map((date) => toDayIn(date, changes[date])) } },
        {
          onSuccess: () => {
            for (const date of changed) delete failed.current[date]
            pending.current -= 1
            if (pending.current === 0) setStatus(Object.keys(failed.current).length ? 'failed' : 'saved')
          },
          onError: (error) => {
            for (const date of changed) failed.current[date] = markOf(marksRef.current, date)
            pending.current -= 1
            setSaveError(errorMessage(error, NETWORK_PROBLEM))
            setStatus('failed')
          },
        },
      )
    },
    // `save.mutate` is stable for the life of the editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [companyId],
  )

  const paint = useCallback(
    (date: string) => {
      if (tool === 'hours' || locked.has(date)) return
      stroke.current ??= {}
      if (date in stroke.current) return
      const before = markOf(marksRef.current, date)
      stroke.current[date] = before
      // A day that already has this state keeps its hours; a tap on it opens the day instead (see endStroke).
      if (before.state !== tool) apply({ [date]: { state: tool, from: null, to: null } })
    },
    [tool, locked],
  )

  const endStroke = useCallback(() => {
    const touched = stroke.current ?? {}
    stroke.current = null
    const changes: Marks = {}
    for (const date of Object.keys(touched)) {
      if (!sameMark(touched[date], markOf(marksRef.current, date))) changes[date] = markOf(marksRef.current, date)
    }
    const touchedDates = Object.keys(touched)
    if (touchedDates.length === 1 && Object.keys(changes).length === 0) {
      // Tapping a day that already shows the chosen state opens it: its hours can be seen and changed.
      setOpenDay(touchedDates[0])
      return
    }
    send(changes)
  }, [send])

  const open = dates.filter((date) => !locked.has(date))
  const counts = countStates(marks, open)
  const today = toIsoDate(new Date())
  const arranged = dates.some((date) => locked.has(date) && date >= today)

  return (
    <div className="grid gap-4">
      {editable && (
        <div className="flex justify-end">
          <SaveIndicator status={status} />
        </div>
      )}

      {arranged && (
        <p className="m-0 text-sm text-ink-muted">
          Na szare dni grafik jest już ułożony, więc ich nie zmienisz. Jeśli coś Ci wypadło, powiedz kierownikowi.
        </p>
      )}

      {status === 'failed' && (
        <div className="grid gap-2">
          <InlineError>{saveError ?? NETWORK_PROBLEM}</InlineError>
          <Button variant="secondary" size="normal" onClick={() => send({ ...failed.current })}>
            Zapisz jeszcze raz
          </Button>
        </div>
      )}

      <AvailabilityCalendar
        start={initial.start}
        end={initial.end}
        marks={marks}
        disabled={!editable}
        locked={locked}
        onPaint={paint}
        onStroke={endStroke}
        onOpenDay={tool === 'hours' ? setOpenDay : undefined}
      />

      <DaysWithHours marks={marks} dates={dates} locked={locked} editable={editable} onOpen={setOpenDay} />

      {open.length > 0 && (
        <p className="m-0 flex flex-wrap gap-x-3.5 gap-y-1 text-sm text-ink-muted" aria-live="polite">
          <span>
            Chętnie: <b className="text-ink tabular-nums">{counts.prefer}</b>
          </span>
          <span>
            Mogę: <b className="text-ink tabular-nums">{counts.neutral}</b>
          </span>
          <span>
            Nie mogę: <b className="text-ink tabular-nums">{counts.cannot}</b>
          </span>
        </p>
      )}

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
                {tool === 'hours' ? 'Stuknij dzień w kalendarzu. Stuknij tu, żeby wrócić.' : 'Gdy możesz tylko przez część dnia'}
              </span>
            </span>
          </button>
          {!period ? (
            <p className="m-0 text-sm text-ink-muted">
              Wszystko zapisuje się samo. Dni, których nie ruszysz, zostają jako „Mogę”.
            </p>
          ) : submittedAt ? (
            <p className="m-0 flex items-start gap-2 rounded-md border-2 border-prefer bg-prefer-soft px-3.5 py-3 text-prefer">
              <Check aria-hidden="true" size={22} className="mt-0.5 flex-none" />
              <span>
                Wysłane do kierownika {dayAndMonth(new Date(submittedAt))}. Dopóki kierownik nie ułoży grafiku, możesz
                jeszcze coś zmienić. Zapisuje się samo.
              </span>
            </p>
          ) : (
            <div className="grid gap-2">
              <Button
                wide
                disabled={submit.isPending}
                onClick={() =>
                  submit.mutate(
                    { data: { company_id: companyId, period_id: period.id } },
                    { onSuccess: (r) => onSubmitted((r.data as MyAvailabilityOut).submitted_at ?? null) },
                  )
                }
              >
                Wyślij kierownikowi
              </Button>
              <p className="m-0 text-sm text-ink-muted">
                Wszystko zapisuje się samo. Dni, których nie ruszysz, zostają jako „Mogę”.
              </p>
              {submit.isError && <InlineError>{errorMessage(submit.error, NETWORK_PROBLEM)}</InlineError>}
            </div>
          )}
        </>
      )}

      {period && period.start <= initial.end && period.end >= initial.start ? (
        <RequestsSection
          companyId={companyId}
          periodId={period.id}
          editable={!readOnly && period.editable}
          assistantReads={assistantReads}
        />
      ) : (
        <RequestsSection
          companyId={companyId}
          month={initial.start}
          editable={!readOnly && initial.end >= today}
          assistantReads={assistantReads}
        />
      )}

      {openDay && (
        <DayHoursSheet
          date={openDay}
          mark={markOf(marks, openDay)}
          onClose={() => setOpenDay(null)}
          onSave={(mark) => {
            const before = markOf(marksRef.current, openDay)
            if (!sameMark(before, mark)) {
              apply({ [openDay]: mark })
              send({ [openDay]: mark })
            }
            setOpenDay(null)
          }}
        />
      )}
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
    <div
      className={
        'sticky bottom-[calc(65px+env(safe-area-inset-bottom))] z-20 -mx-4 border-t border-line bg-paper px-4 pt-2 pb-2.5 md:bottom-0 ' +
        // A short phone screen keeps more of the calendar in sight; lying on its side, the bar scrolls with the page.
        '[@media(max-height:800px)]:pt-1.5 [@media(max-height:800px)]:pb-1.5 [@media(max-height:500px)]:static'
      }
    >
      <p
        className={cn('m-0 mb-1.5 text-sm font-semibold', tool !== 'hours' && '[@media(max-height:800px)]:sr-only')}
        id="tool-label"
      >
        {tool === 'hours' ? 'Stuknij dzień, żeby ustawić godziny.' : 'Wybierz, a potem zaznacz dni:'}
      </p>
      <div role="group" aria-labelledby="tool-label" className="grid grid-cols-3 gap-1.5">
        {STATES.map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={tool === t}
            onClick={() => onChange(t)}
            className={cn(
              'grid min-h-16 min-w-0 cursor-pointer place-items-center gap-0.5 rounded-md border-2 border-line bg-surface px-0.5 py-1.5 text-sm font-semibold',
              '[@media(max-height:800px)]:flex [@media(max-height:800px)]:min-h-(--touch) [@media(max-height:800px)]:justify-center [@media(max-height:800px)]:gap-1.5 [@media(max-height:800px)]:py-1',
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
  locked,
  editable,
  onOpen,
}: {
  marks: Marks
  dates: string[]
  locked: Set<string>
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
            {editable && !locked.has(date) && (
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
