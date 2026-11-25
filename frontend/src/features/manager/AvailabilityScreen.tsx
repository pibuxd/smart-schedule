import { useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import {
  useAvailabilityGrid,
  useEndRequest,
  usePeriodRequests,
  useRereadRequest,
  useUpdateRequest,
} from '../../api/generated/availability/availability'
import type {
  AvailabilityGridOut,
  LocationOut,
  ManagerRequestOut,
  ManagerRequestOutManagerPriority,
  PeriodOut,
} from '../../api/generated/model'
import {
  getLocationPeriodsQueryKey,
  useCreatePeriod,
  useDeletePeriod,
  useLocationPeriods,
  useUpdatePeriod,
} from '../../api/generated/scheduling/scheduling'
import { useLocationDetail } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { ConfirmSheet } from '../../components/ui/confirm'
import { Section, SelectField, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { sinceWords } from '../../lib/dates'
import { AssistantRulesTable } from './AssistantRulesTable'
import { AskAvailabilityButton } from './AskAvailabilityButton'
import { AvailabilityGrid, GridLegend } from './AvailabilityGrid'
import { useManager } from './ManagerContext'
import { nextPeriodDates, pickPeriod, useChosenPeriod } from './periods'
import { Progress } from './OverviewScreen'
import { daysUntil, deadlineWords, namesList, PERIOD_STATUS, periodTitle, shortDay } from './words'

export function AvailabilityOverviewScreen({ locationId, today = new Date() }: { locationId: string; today?: Date }) {
  const periods = useLocationPeriods(locationId)
  const [chosen, setChosen] = useChosenPeriod(locationId)
  const [adding, setAdding] = useState(false)

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

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {list.length > 1 && period ? (
          <SelectField
            label="Okres grafiku"
            value={period.id}
            onChange={(e) => setChosen(e.target.value)}
            className="min-w-64"
          >
            {[...list]
              .sort((a, b) => b.start.localeCompare(a.start))
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {periodTitle(p.start, p.end)} ({PERIOD_STATUS[p.status].toLowerCase()})
                </option>
              ))}
          </SelectField>
        ) : (
          <span />
        )}
        <Button variant="secondary" size="normal" onClick={() => setAdding(true)}>
          <CalendarPlus aria-hidden="true" size={20} />
          Nowy okres grafiku
        </Button>
      </div>

      {period ? (
        <PeriodView key={period.id} period={period} today={today} />
      ) : (
        <EmptyState title="Nie ma jeszcze okresu grafiku">
          <p className="m-0">
            Ustal daty grafiku i termin dyspozycji.
          </p>
          <Button onClick={() => setAdding(true)}>Ustal daty grafiku</Button>
        </EmptyState>
      )}
      <NewPeriodSheet open={adding} onOpenChange={setAdding} locationId={locationId} periods={list} onCreated={setChosen} />
    </div>
  )
}

function PeriodView({ period, today }: { period: PeriodOut; today: Date }) {
  const grid = useAvailabilityGrid(period.id)
  const { readOnly } = useManager()
  if (grid.isPending) return <Loading>Wczytuję dyspozycje…</Loading>
  if (grid.isError) {
    return (
      <ErrorState onRetry={() => void grid.refetch()}>
        {errorMessage(grid.error, 'Nie udało się wczytać dyspozycji. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = grid.data.data as AvailabilityGridOut
  const missing = data.employees.filter((e) => !e.submitted_at)
  const late = data.employees.filter((e) => e.late_days > 0)
  const collecting = period.status === 'collecting'
  const total = data.employees.length
  const passed = daysUntil(period.deadline, today) < 0

  return (
    <div className="grid gap-8">
      <section className="grid gap-5 rounded-md border border-line bg-surface p-4 md:grid-cols-[1.2fr_1fr_auto]">
        <div className="grid content-start gap-2">
          <h2 className="m-0 text-xl font-extrabold">Grafik {periodTitle(period.start, period.end)}</h2>
          <span>
            <Tag tone={collecting ? 'accent' : 'muted'}>{PERIOD_STATUS[period.status]}</Tag>
          </span>
          <DeadlineEditor period={period} today={today} disabled={readOnly || !collecting} />
          {period.status !== 'published' && <DeletePeriod period={period} disabled={readOnly} />}
        </div>
        <div className="grid content-start gap-2">
          <Progress done={total - missing.length} total={total} />
          {collecting && total > 0 && missing.length === 0 && (
            <p className="m-0 font-semibold text-accent">Wszyscy wysłali dyspozycje. Możesz układać grafik.</p>
          )}
          {collecting && passed && missing.length > 0 && (
            <p className="m-0 font-semibold text-accent">
              Termin minął. Możesz układać grafik. Kto nie wysłał, może dostać zmianę w każdy dzień.
            </p>
          )}
          {period.availability_requested_at && (
            <p className="m-0 text-sm text-ink-muted">
              Prośba wysłana {shortDay(period.availability_requested_at.slice(0, 10))}.
            </p>
          )}
        </div>
        {collecting && (
          <AskAvailabilityButton
            periodId={period.id}
            missing={missing.length}
            asked={period.availability_requested_at !== null}
            disabled={readOnly}
          />
        )}
      </section>

      {missing.length > 0 && (
        <Section
          title={`Jeszcze nie wysłali (${missing.length})`}
          description="Nie nacisnęli jeszcze „Wyślij kierownikowi”."
        >
          <p className="m-0">{namesList(missing.map((e) => e.name), 12)}</p>
        </Section>
      )}

      {late.length > 0 && (
        <Section
          title={`Zmienione po terminie (${late.length})`}
          collapsible
          description="Te dni mają w tabeli znak zegara."
        >
          <ul className="m-0 grid list-none gap-1 p-0">
            {late.map((e) => (
              <li key={e.id}>
                <b>{e.name}</b>: {e.late_days === 1 ? '1 dzień' : `${e.late_days} dni`}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Kto kiedy może" description="Przewiń tabelę w bok, żeby zobaczyć kolejne dni.">
        <GridLegend />
        {total === 0 ? (
          <EmptyState title="Nikt jeszcze nie pracuje w tym lokalu">
            <p className="m-0">Zaproś pracowników w zakładce „Pracownicy”. Pojawią się tutaj, gdy przyjmą zaproszenie.</p>
          </EmptyState>
        ) : (
          <AvailabilityGrid data={data} />
        )}
      </Section>

      <AssistantRulesTable locationId={period.location_id} periodId={period.id} />
      <RequestsSection periodId={period.id} />
    </div>
  )
}

/** For a period added by mistake (e.g. wrong dates). A period whose schedule was published stays. */
function DeletePeriod({ period, disabled }: { period: PeriodOut; disabled: boolean }) {
  const remove = useDeletePeriod()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  return (
    <div>
      <Button variant="quiet" size="normal" disabled={disabled} onClick={() => setOpen(true)}>
        <Trash2 aria-hidden="true" size={18} />
        Usuń ten okres
      </Button>
      <ConfirmSheet
        open={open}
        onOpenChange={setOpen}
        title="Usunąć ten okres grafiku?"
        confirmLabel="Tak, usuń okres"
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(
            { periodId: period.id },
            {
              onSuccess: async () => {
                // The list first, so this period's view is gone before its own data is asked for again.
                await queryClient.invalidateQueries({ queryKey: getLocationPeriodsQueryKey(period.location_id) })
                void queryClient.invalidateQueries()
              },
            },
          )
        }
      >
        <p className="m-0">
          {`Okres ${periodTitle(period.start, period.end)} zniknie razem ze szkicem grafiku, Twoimi ręcznymi poprawkami i prośbami pracowników na ten okres. `}
          Zaznaczone w kalendarzu dyspozycje zostają.
        </p>
      </ConfirmSheet>
    </div>
  )
}

function DeadlineEditor({ period, today, disabled }: { period: PeriodOut; today: Date; disabled: boolean }) {
  const update = useUpdatePeriod()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(period.deadline)

  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-x-2">
        <span>
          Termin dyspozycji: <b>{shortDay(period.deadline)}</b>
          {period.status === 'collecting' && <span className="text-ink-muted"> ({deadlineWords(period.deadline, today)})</span>}
        </span>
        {!disabled && (
          <Button variant="quiet" size="normal" onClick={() => setEditing(true)}>
            Zmień
          </Button>
        )}
      </div>
    )
  }
  const save = (event: React.FormEvent) => {
    event.preventDefault()
    update.mutate(
      { periodId: period.id, data: { availability_deadline: value } },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries()
          setEditing(false)
        },
      },
    )
  }
  return (
    <form onSubmit={save} className="grid gap-2">
      <TextField
        label="Do kiedy pracownicy wpisują dyspozycje"
        type="date"
        value={value}
        max={period.start}
        onChange={(e) => setValue(e.target.value)}
        required
      />
      {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
      <div className="flex gap-2">
        <Button type="submit" size="normal" disabled={update.isPending}>
          Zapisz termin
        </Button>
        <Button variant="quiet" size="normal" onClick={() => setEditing(false)}>
          Anuluj
        </Button>
      </div>
    </form>
  )
}

function NewPeriodSheet({
  open,
  onOpenChange,
  locationId,
  periods,
  onCreated,
  today = new Date(),
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  locationId: string
  periods: PeriodOut[]
  onCreated: (id: string) => void
  today?: Date
}) {
  const location = useLocationDetail(locationId)
  const data = location.data?.data as LocationOut | undefined
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Nowy okres grafiku"
    >
      {data && (
        <NewPeriodForm
          key={periods.length}
          defaults={nextPeriodDates(data, periods, today)}
          locationId={locationId}
          onDone={(id) => {
            onCreated(id)
            onOpenChange(false)
          }}
        />
      )}
    </Sheet>
  )
}

function NewPeriodForm({
  defaults,
  locationId,
  onDone,
}: {
  defaults: { start: string; end: string; deadline: string }
  locationId: string
  onDone: (id: string) => void
}) {
  const create = useCreatePeriod()
  const queryClient = useQueryClient()
  const [start, setStart] = useState(defaults.start)
  const [end, setEnd] = useState(defaults.end)
  const [deadline, setDeadline] = useState(defaults.deadline)
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(
      { locationId, data: { start, end, availability_deadline: deadline } },
      {
        onSuccess: (response) => {
          void queryClient.invalidateQueries()
          onDone((response.data as PeriodOut).id)
        },
      },
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Od" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
        <TextField label="Do" type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} required />
      </div>
      <TextField
        label="Termin dyspozycji"
        type="date"
        value={deadline}
        max={start}
        onChange={(e) => setDeadline(e.target.value)}
        required
        hint="Ostatni dzień na wpisanie dyspozycji."
      />
      {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={create.isPending}>
        Zapisz
      </Button>
    </form>
  )
}

// --------------------------------------------------------------------------------------------- requests

const PRIORITY: { value: ManagerRequestOutManagerPriority; label: string }[] = [
  { value: 'lower', label: 'Mniej ważna' },
  { value: 'normal', label: 'Zwykła' },
  { value: 'higher', label: 'Ważniejsza' },
]

function RequestsSection({ periodId }: { periodId: string }) {
  const requests = usePeriodRequests(periodId, {
    query: {
      // While the assistant reads a request (a few seconds), look again.
      refetchInterval: (query) =>
        ((query.state.data?.data as ManagerRequestOut[] | undefined) ?? []).some((r) => r.status === 'new') ? 2000 : false,
    },
  })
  if (requests.isPending) return <Loading>Wczytuję prośby…</Loading>
  if (requests.isError) {
    return (
      <ErrorState onRetry={() => void requests.refetch()}>
        {errorMessage(requests.error, 'Nie udało się wczytać próśb. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const list = requests.data.data as ManagerRequestOut[]
  return (
    <Section
      title={`Prośby pracowników (${list.length})`}
      description="Czego nie dało się zaznaczyć w kalendarzu. Widzisz je tylko Ty."
    >
      {list.length === 0 ? (
        <EmptyState title="Nikt nie napisał prośby">
          <p className="m-0">Gdy pracownik napisze coś w „Coś jeszcze?”, zobaczysz to tutaj.</p>
        </EmptyState>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0 lg:grid-cols-2">
          {list.map((r) => (
            <RequestCard key={r.id} request={r} periodId={periodId} />
          ))}
        </ul>
      )}
    </Section>
  )
}

function requestNote(request: ManagerRequestOut): string {
  if (request.summary) return `Jak to zrozumiał asystent: ${request.summary} Generator weźmie to pod uwagę.`
  if (request.status === 'new') return 'Asystent właśnie czyta tę prośbę.'
  const yourself =
    'przeczytaj ją sam i, jeśli chcesz ją spełnić, popraw grafik ręcznie albo napisz polecenie asystentowi.'
  const canYourself =
    'Możesz przeczytać ją sam i, jeśli chcesz ją spełnić, poprawić grafik ręcznie albo napisać polecenie asystentowi.'
  if (request.unread_reason === 'off') {
    return request.can_reread
      ? `Ta prośba przyszła, kiedy asystent był wyłączony, więc jeszcze jej nie czytał. Daj mu ją albo ${yourself}`
      : `Asystent jest wyłączony, więc generator nie bierze tej prośby pod uwagę. ${canYourself}`
  }
  if (request.unread_reason === 'failed') {
    return `Asystent nie zdołał przeczytać tej prośby (błąd połączenia). Spróbuj jeszcze raz albo ${yourself}`
  }
  if (request.unread_reason === 'rejected') {
    return `Asystent odrzucił tę wiadomość jako niezwiązaną z grafikiem. Pracownik przekazał ją Tobie do oceny. Generator jej nie bierze pod uwagę. ${canYourself}`
  }
  if (request.employee_corrected) return `Pracownik napisał, że asystent źle to zrozumiał. ${canYourself}`
  return `Asystent przeczytał tę prośbę, ale nie umiał zamienić jej na coś, co generator sprawdzi sam. ${canYourself}`
}

/**
 * A request "na stałe" written for an earlier period: it counts here too, and the manager can end it from this
 * period on. Once ended from here it stays on the list, with "Przywróć" when a manager ended it.
 */
function LastingControls({ request, periodId }: { request: ManagerRequestOut; periodId: string }) {
  const end = useEndRequest()
  const queryClient = useQueryClient()
  const { readOnly } = useManager()
  const send = (ended: boolean) =>
    end.mutate(
      { periodId, requestId: request.id, data: { ended } },
      { onSuccess: () => void queryClient.invalidateQueries() },
    )
  if (request.ended) {
    return (
      <div className="grid gap-2">
        <p className="m-0 text-sm text-ink-muted">
          {request.ended_by === 'manager'
            ? 'Zakończona od tego okresu: generator już jej nie bierze pod uwagę. Pracownik dostał powiadomienie.'
            : 'Pracownik zakończył tę prośbę od tego okresu: generator już jej nie bierze pod uwagę.'}
        </p>
        {request.ended_by === 'manager' && (
          <div>
            <Button variant="quiet" size="normal" disabled={readOnly || end.isPending} onClick={() => send(false)}>
              Przywróć prośbę
            </Button>
          </div>
        )}
        {end.isError && <InlineError>{errorMessage(end.error, NETWORK_PROBLEM)}</InlineError>}
      </div>
    )
  }
  return (
    <>
      <Button variant="quiet" size="normal" disabled={readOnly || end.isPending} onClick={() => send(true)}>
        Zakończ od tego okresu
      </Button>
      {end.isError && <InlineError>{errorMessage(end.error, NETWORK_PROBLEM)}</InlineError>}
    </>
  )
}

export function RequestCard({ request, periodId }: { request: ManagerRequestOut; periodId?: string }) {
  const update = useUpdateRequest()
  const reread = useRereadRequest()
  const queryClient = useQueryClient()
  const { readOnly } = useManager()
  const change = (data: { manager_priority?: ManagerRequestOutManagerPriority; manager_rejected?: boolean }) =>
    update.mutate({ requestId: request.id, data }, { onSuccess: () => void queryClient.invalidateQueries() })
  const rejected = request.manager_rejected
  const carried = Boolean(request.carried_from) && periodId !== undefined
  const ended = carried && Boolean(request.ended)
  if (ended)
    return (
      <li className="grid gap-3 rounded-md border border-dashed border-line bg-paper p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <b>{request.employee_name}</b>
          <Tag>Zakończona</Tag>
        </div>
        <p className="m-0 text-ink-muted">„{request.text}”</p>
        <LastingControls request={request} periodId={periodId!} />
      </li>
    )
  return (
    <li className={rejected ? 'grid gap-3 rounded-md border border-dashed border-line bg-paper p-4' : 'grid gap-3 rounded-md border border-line bg-surface p-4'}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b>{request.employee_name}</b>
        <span className="flex flex-wrap gap-1">
          {request.lasting && (
            <Tag tone="accent">
              {request.carried_from ? `Na stałe ${sinceWords(request.carried_from)}` : 'Na stałe'}
            </Tag>
          )}
          {rejected && <Tag tone="bad">Odrzucona</Tag>}
        </span>
      </div>
      {/* The earlier messages of this request: the text below answers the assistant's last question. */}
      {(request.exchange ?? []).map((earlier, i) => (
        <p key={i} className="m-0 text-sm text-ink-muted">
          {i === 0 ? 'Wcześniej' : 'Potem'}: „{earlier.text}” Asystent zapytał: „{earlier.question}”
        </p>
      ))}
      <p className={rejected ? 'm-0 text-ink-muted line-through' : 'm-0'}>„{request.text}”</p>
      <p className="m-0 text-sm text-ink-muted">{requestNote(request)}</p>
      {request.employee_corrected && request.summary && (
        <p className="m-0 text-sm text-ink-muted">Pracownik poprawił tę prośbę po tym, jak przeczytał ją asystent.</p>
      )}
      {request.can_reread && !readOnly && (
        <div>
          <Button
            variant="secondary"
            size="normal"
            disabled={reread.isPending}
            onClick={() =>
              reread.mutate({ requestId: request.id }, { onSuccess: () => void queryClient.invalidateQueries() })
            }
          >
            {reread.isPending ? 'Wysyłam…' : 'Daj asystentowi do przeczytania'}
          </Button>
          <p className="m-0 mt-1 text-sm text-ink-muted">
            Treść prośby trafi wtedy do zewnętrznej usługi AI.
            {request.unread_reason === 'off' &&
              ' Pracownik pisał ją, kiedy asystent był wyłączony, więc dostanie o tym powiadomienie.'}
          </p>
        </div>
      )}
      {reread.isError && <InlineError>{errorMessage(reread.error, NETWORK_PROBLEM)}</InlineError>}
      {!rejected && (
        <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0" disabled={readOnly || update.isPending}>
          <legend className="sr-only">Ważność prośby</legend>
          {PRIORITY.map((p) => (
            <button
              key={p.value}
              type="button"
              aria-pressed={request.manager_priority === p.value}
              onClick={() => change({ manager_priority: p.value })}
              className={
                'min-h-(--touch) cursor-pointer rounded-sm border-2 px-3 text-sm font-semibold ' +
                (request.manager_priority === p.value
                  ? 'border-accent bg-accent text-accent-ink'
                  : 'border-line bg-surface text-ink hover:border-accent')
              }
            >
              {p.label}
            </button>
          ))}
        </fieldset>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant={rejected ? 'quiet' : 'danger'}
          size="normal"
          disabled={readOnly || update.isPending}
          onClick={() => change({ manager_rejected: !rejected })}
        >
          {rejected ? 'Przywróć prośbę' : 'Odrzuć prośbę'}
        </Button>
        {carried && request.lasting && <LastingControls request={request} periodId={periodId!} />}
      </div>
      {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
    </li>
  )
}

