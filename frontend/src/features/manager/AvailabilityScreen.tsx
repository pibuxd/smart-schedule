import { useQueryClient } from '@tanstack/react-query'
import { CalendarPlus } from 'lucide-react'
import { useState } from 'react'

import { useAvailabilityGrid, usePeriodRequests, useUpdateRequest } from '../../api/generated/availability/availability'
import type {
  AvailabilityGridOut,
  LocationOut,
  ManagerRequestOut,
  ManagerRequestOutManagerPriority,
  PeriodOut,
} from '../../api/generated/model'
import { useCreatePeriod, useLocationPeriods, useUpdatePeriod } from '../../api/generated/scheduling/scheduling'
import { useLocationDetail } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { Section, SelectField, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { AskAvailabilityButton } from './AskAvailabilityButton'
import { AvailabilityGrid, GridLegend } from './AvailabilityGrid'
import { useManager } from './ManagerContext'
import { nextPeriodDates, pickPeriod } from './periods'
import { Progress } from './OverviewScreen'
import { daysUntil, deadlineWords, namesList, PERIOD_STATUS, periodTitle, shortDay } from './words'

export function AvailabilityOverviewScreen({ locationId, today = new Date() }: { locationId: string; today?: Date }) {
  const periods = useLocationPeriods(locationId)
  const [chosen, setChosen] = useState<string | null>(null)
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
            Ustal daty okresu i termin, do którego pracownicy wpisują dyspozycje. Potem poproś ich o to jednym
            przyciskiem.
          </p>
          <Button onClick={() => setAdding(true)}>Ustal okres grafiku</Button>
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
        </div>
        <div className="grid content-start gap-2">
          <Progress done={total - missing.length} total={total} />
          {collecting && total > 0 && missing.length === 0 && (
            <p className="m-0 font-semibold text-accent">Wszyscy wpisali dyspozycje. Można układać grafik.</p>
          )}
          {collecting && passed && missing.length > 0 && (
            <p className="m-0 font-semibold text-accent">
              Termin minął. Można układać grafik; osoby bez dyspozycji liczą się jak „obojętnie”.
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
        <Section title={`Jeszcze nie wpisali (${missing.length})`}>
          <p className="m-0">{namesList(missing.map((e) => e.name), 12)}</p>
        </Section>
      )}

      {late.length > 0 && (
        <Section
          title="Zmienione po terminie"
          description="Pracownicy mogą poprawiać dyspozycje aż do ułożenia grafiku. Te dni zmienili po terminie; w siatce mają znak zegara."
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

      <Section title="Siatka dyspozycji" description="Przewiń tabelę w bok, żeby zobaczyć kolejne dni.">
        <GridLegend />
        {total === 0 ? (
          <EmptyState title="Nikt jeszcze nie pracuje w tym lokalu">
            <p className="m-0">Zaproś pracowników na karcie „Pracownicy”. Po przyjęciu zaproszenia pojawią się tutaj.</p>
          </EmptyState>
        ) : (
          <AvailabilityGrid data={data} />
        )}
      </Section>

      <RequestsSection periodId={period.id} />
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
        label="Termin dyspozycji (dzień, w którym ułożysz grafik)"
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
      description="Wpisz daty grafiku i dzień, w którym będziesz go układać. Do tego dnia pracownicy wpisują dyspozycje."
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
        hint="Ostatni dzień na wpisanie dyspozycji. Grafik ułożysz po nim, gdy będziesz mieć komplet."
      />
      {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={create.isPending}>
        Utwórz okres
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
  const requests = usePeriodRequests(periodId)
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
      description="Sprawy, których nie da się zaznaczyć w kalendarzu. Widzisz je tylko Ty. Możesz prośbę odrzucić albo uznać za ważniejszą lub mniej ważną."
    >
      {list.length === 0 ? (
        <EmptyState title="Nikt nie dopisał prośby">
          <p className="m-0">Gdy pracownik napisze coś w „Coś jeszcze?”, zobaczysz to tutaj.</p>
        </EmptyState>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0 lg:grid-cols-2">
          {list.map((r) => (
            <RequestCard key={r.id} request={r} />
          ))}
        </ul>
      )}
    </Section>
  )
}

function RequestCard({ request }: { request: ManagerRequestOut }) {
  const update = useUpdateRequest()
  const queryClient = useQueryClient()
  const { readOnly } = useManager()
  const change = (data: { manager_priority?: ManagerRequestOutManagerPriority; manager_rejected?: boolean }) =>
    update.mutate({ requestId: request.id, data }, { onSuccess: () => void queryClient.invalidateQueries() })
  const rejected = request.manager_rejected
  return (
    <li className={rejected ? 'grid gap-3 rounded-md border border-dashed border-line bg-paper p-4' : 'grid gap-3 rounded-md border border-line bg-surface p-4'}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b>{request.employee_name}</b>
        {rejected && <Tag tone="bad">Odrzucona</Tag>}
      </div>
      <p className={rejected ? 'm-0 text-ink-muted line-through' : 'm-0'}>„{request.text}”</p>
      <p className="m-0 text-sm text-ink-muted">
        {request.summary
          ? `Jak to zrozumiał asystent: ${request.summary}`
          : 'Asystent jeszcze tej prośby nie przeczytał, więc przy układaniu grafiku zostaje do Twojej oceny.'}
      </p>
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
      <div>
        <Button
          variant={rejected ? 'quiet' : 'danger'}
          size="normal"
          disabled={readOnly || update.isPending}
          onClick={() => change({ manager_rejected: !rejected })}
        >
          {rejected ? 'Przywróć prośbę' : 'Odrzuć prośbę'}
        </Button>
      </div>
      {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
    </li>
  )
}

