// Rates and supplements (docs/plan.md, sections 35 and 42): a rate counts from a chosen day, so a change never moves
// the pay of earlier months. Used by "Stanowiska" and "Dodatki do stawek" in the location settings and "Stawki" in
// the employee form.

import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type {
  PaySettingsOut,
  PersonalRateOut,
  PositionOut,
  RateIn,
  SupplementIn,
  SupplementOut,
  SupplementOutKind,
} from '../../api/generated/model'
import {
  useCreateSupplement,
  useDeletePersonalRate,
  useDeletePositionRate,
  useEndSupplement,
  usePaySettings,
  usePersonalRates,
  useSetPersonalRate,
  useSetPositionRate,
  useUpdateSupplement,
} from '../../api/generated/pay/pay'
import { useDeletePosition, useUpdatePosition } from '../../api/generated/staffing/staffing'
import { Button } from '../../components/ui/button'
import { ConfirmSheet } from '../../components/ui/confirm'
import { Disclosure } from '../../components/ui/disclosure'
import { CheckField, Section, SelectField, TextField } from '../../components/ui/field'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { shortTime, toIsoDate, WEEKDAY_HEADERS } from '../../lib/dates'
import {
  BAD_RATE,
  byDay,
  fullDay,
  inPastMonth,
  PAST_MONTHS,
  parseRate,
  rateInput,
  rateText,
  type RateStep,
  stepOn,
  stepsAfter,
} from '../../lib/money'
import { useManager } from './ManagerContext'

const hhmm = (value: string) => value.slice(0, 5)

/** A warning under a form: what saving it will do that is easy to miss. */
function WarningNote({ children }: { children: string }) {
  return (
    <p className="m-0 flex basis-full items-center gap-2 text-sm font-semibold">
      <AlertTriangle aria-hidden="true" size={16} className="shrink-0 text-cannot" />
      {children}
    </p>
  )
}

/** Said next to a day before this month: the change reaches pay that may already be paid. */
const PastMonthsNote = () => <WarningNote>{PAST_MONTHS}</WarningNote>

const NO_RATE_FROM_DAY = 'Puste pole: od tego dnia stanowisko będzie bez stawki, a godziny bez wypłaty.'

// --------------------------------------------------------------------------------------------- rate steps

const stepAmount = (step: RateStep | undefined, fallback: string) =>
  step?.hourly_rate != null ? rateText(step.hourly_rate) : fallback

const fromWords = (step: RateStep) => (step.valid_from ? `od ${fullDay(step.valid_from)}` : 'od początku')

/** The rate that counts today, and the changes entered ahead ("Od 1 stycznia 2027: 33,00 zł/h"). */
export function RateNow({ steps, today, fallback }: { steps: RateStep[]; today: string; fallback: string }) {
  return (
    <span className="grid min-h-(--touch) content-center">
      <span className="tabular-nums">{stepAmount(stepOn(steps, today), fallback)}</span>
      {stepsAfter(steps, today).map((s) => (
        <span key={s.id} className="text-sm tabular-nums">{`Od ${fullDay(s.valid_from ?? today)}: ${stepAmount(s, fallback)}`}</span>
      ))}
    </span>
  )
}

/** "Zmiany stawki (n)": every step with "Usuń" (a step before this month asks first). */
function RateHistory({
  name,
  steps,
  fallback,
  today,
  disabled,
  onDelete,
}: {
  name: string
  steps: RateStep[]
  fallback: string
  today: string
  disabled: boolean
  onDelete: (id: string) => void
}) {
  const [removing, setRemoving] = useState<RateStep | null>(null)
  if (steps.length === 0) return null
  return (
    <>
      <Disclosure summary={<span className="text-sm">{`Zmiany stawki (${steps.length})`}</span>}>
        <ul className="m-0 grid list-none gap-1 p-0 pb-2">
          {[...steps].sort(byDay).map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="tabular-nums">{`${fromWords(s)}: ${stepAmount(s, fallback)}`}</span>
              <Button
                variant="quiet"
                size="normal"
                disabled={disabled}
                aria-label={`Usuń stawkę ${name} ${fromWords(s)}`}
                onClick={() => (inPastMonth(s.valid_from, today) ? setRemoving(s) : onDelete(s.id))}
              >
                Usuń
              </Button>
            </li>
          ))}
        </ul>
      </Disclosure>
      <ConfirmSheet
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Usunąć stawkę ${removing ? fromWords(removing) : ''}?`}
        confirmLabel="Tak, usuń stawkę"
        onConfirm={() => {
          if (removing) onDelete(removing.id)
          setRemoving(null)
        }}
      >
        <p className="m-0">{PAST_MONTHS}</p>
      </ConfirmSheet>
    </>
  )
}

/** One rate by day: what counts today, changes entered ahead, "Zmień stawkę" from a day, and the steps to fix. */
export function RateSteps({
  name,
  steps,
  fallback,
  emptyHint,
  firstForAll = true,
  today,
  disabled,
  pending,
  error,
  onSave,
  onDelete,
}: {
  /** What the rate is for, in button labels: "Sprzedawca". */
  name: string
  steps: RateStep[]
  /** What counts without an amount: "bez stawki", or the position's rate for a person. */
  fallback: string
  /** What an empty amount means, under the field: "Puste pole: znowu stawka stanowiska." */
  emptyHint?: string
  /** The first step counts for every shift (a position). A person's first own rate is a change from a day. */
  firstForAll?: boolean
  today: string
  disabled: boolean
  pending: boolean
  error: unknown
  onSave: (data: RateIn, done: () => void) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [rate, setRate] = useState('')
  const [from, setFrom] = useState(today)
  const [bad, setBad] = useState(false)
  const now = stepOn(steps, today)
  const first = steps.length === 0 && firstForAll

  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-start justify-between gap-x-3">
        <RateNow steps={steps} today={today} fallback={fallback} />
        {!editing && (
          <Button
            variant="quiet"
            size="normal"
            disabled={disabled}
            aria-label={`Zmień stawkę: ${name}`}
            onClick={() => {
              setRate(rateInput(now?.hourly_rate))
              setFrom(today)
              setBad(false)
              setEditing(true)
            }}
          >
            Zmień stawkę
          </Button>
        )}
      </div>
      {editing && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            const value = parseRate(rate)
            setBad(Number.isNaN(value))
            if (Number.isNaN(value)) return
            onSave({ hourly_rate: value, valid_from: first ? null : from }, () => setEditing(false))
          }}
        >
          <TextField
            label="Stawka, zł/h"
            className="w-32"
            inputMode="decimal"
            placeholder="np. 34,00"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          />
          {!first && (
            <TextField label="Od dnia" type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
          )}
          <Button type="submit" size="normal" disabled={pending}>
            Zapisz stawkę
          </Button>
          <Button variant="quiet" size="normal" onClick={() => setEditing(false)}>
            Anuluj
          </Button>
          {!first && from && inPastMonth(from, today) && <PastMonthsNote />}
          {first && <p className="m-0 basis-full text-sm text-ink-muted">Pierwsza stawka liczy się dla wszystkich zmian.</p>}
          {emptyHint && steps.length > 0 && <p className="m-0 basis-full text-sm text-ink-muted">{emptyHint}</p>}
          {bad && <InlineError>{BAD_RATE}</InlineError>}
          {Boolean(error) && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
        </form>
      )}
      <RateHistory name={name} steps={steps} fallback={fallback} today={today} disabled={disabled} onDelete={onDelete} />
    </div>
  )
}

// --------------------------------------------------------------------------------------------- settings

/** "Zmień" at a position in "Stanowiska i stawki": its name and its rate from a day in one form, the steps to fix,
 * and removing the position. */
export function PositionForm({
  position,
  steps,
  today,
  onDone,
}: {
  position: PositionOut
  steps: RateStep[]
  today: string
  onDone: () => void
}) {
  const rename = useUpdatePosition()
  const save = useSetPositionRate()
  const removeRate = useDeletePositionRate()
  const remove = useDeletePosition()
  const queryClient = useQueryClient()
  const refresh = () => void queryClient.invalidateQueries()
  const now = stepOn(steps, today)
  const first = steps.length === 0
  const [name, setName] = useState(position.name)
  const [rate, setRate] = useState(rateInput(now?.hourly_rate))
  const [from, setFrom] = useState(today)
  const [bad, setBad] = useState(false)
  const [removing, setRemoving] = useState(false)
  const error = rename.error ?? save.error ?? removeRate.error ?? remove.error

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const value = parseRate(rate)
    setBad(Number.isNaN(value))
    if (Number.isNaN(value)) return
    // A new step only when the amount differs from what already counts on that day.
    const newRate = first ? value !== null : value !== (stepOn(steps, from)?.hourly_rate ?? null)
    try {
      if (name.trim() !== position.name) await rename.mutateAsync({ positionId: position.id, data: { name: name.trim() } })
      if (newRate) {
        await save.mutateAsync({ positionId: position.id, data: { hourly_rate: value, valid_from: first ? null : from } })
      }
    } catch {
      return // the error shows under the form
    } finally {
      refresh()
    }
    onDone()
  }

  return (
    <div className="grid gap-4">
      <form onSubmit={(e) => void submit(e)} className="grid gap-4">
        <TextField label="Nazwa" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Stawka, zł/h"
            inputMode="decimal"
            placeholder="np. 34,00"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          />
          {!first && <TextField label="Od dnia" type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />}
        </div>
        {first ? (
          <p className="m-0 text-sm text-ink-muted">Pierwsza stawka liczy się dla wszystkich zmian.</p>
        ) : (
          <p className="m-0 text-sm text-ink-muted">Zmiany przed tym dniem zostają przy starej stawce.</p>
        )}
        {!first && from && inPastMonth(from, today) && <PastMonthsNote />}
        {/* An emptied field ends the rate from that day: said before saving, since it is easy to do by mistake. */}
        {!first && rate.trim() === '' && stepOn(steps, from)?.hourly_rate != null && (
          <WarningNote>{NO_RATE_FROM_DAY}</WarningNote>
        )}
        {bad && <InlineError>{BAD_RATE}</InlineError>}
        {Boolean(error) && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
        <Button type="submit" wide disabled={rename.isPending || save.isPending}>
          Zapisz stanowisko
        </Button>
      </form>
      <RateHistory
        name={position.name}
        steps={steps}
        fallback="bez stawki"
        today={today}
        disabled={removeRate.isPending}
        onDelete={(rateId) => removeRate.mutate({ rateId }, { onSuccess: refresh })}
      />
      {!removing ? (
        <Button variant="danger" wide onClick={() => setRemoving(true)}>
          <Trash2 aria-hidden="true" size={18} />
          Usuń to stanowisko
        </Button>
      ) : (
        <div role="alert" className="grid gap-3 rounded-md border border-cannot bg-surface p-4">
          <p className="m-0">
            <b>{`Usunąć stanowisko „${position.name}”?`}</b> Zniknie z obsady i z wyjątków.
            {position.employees > 0 ? ` Stracą je też osoby, które je mają (${position.employees}).` : ''} W ułożonych
            już grafikach zostaje.
          </p>
          <Button
            variant="danger"
            wide
            disabled={remove.isPending}
            onClick={() => remove.mutate({ positionId: position.id }, { onSuccess: () => { refresh(); onDone() } })}
          >
            Tak, usuń stanowisko
          </Button>
          <Button variant="secondary" wide onClick={() => setRemoving(false)}>
            Zostaw
          </Button>
        </div>
      )}
    </div>
  )
}

/** "Dodatki do stawek" in the location settings, right under "Stanowiska" (where the rates are). */
export function SupplementsSection({ locationId, today = new Date() }: { locationId: string; today?: Date }) {
  const settings = usePaySettings(locationId)
  const day = toIsoDate(today)
  const data = settings.data?.data as PaySettingsOut | undefined
  const live = data ? data.supplements.filter((s) => !s.valid_until || s.valid_until >= day).length : 0
  const status = data ? (live ? `dodatki: ${live}` : 'bez dodatków') : undefined

  return (
    <Section
      title="Dodatki do stawek"
      collapsible
      status={status}
      description="Np. za noc albo niedzielę. Liczy się tylko część zmiany w tych godzinach."
    >
      {settings.isPending ? (
        <Loading>Wczytuję dodatki…</Loading>
      ) : settings.isError || !data ? (
        <ErrorState onRetry={() => void settings.refetch()}>
          {errorMessage(settings.error, 'Nie udało się wczytać dodatków. Spróbuj jeszcze raz.')}
        </ErrorState>
      ) : (
        <Supplements locationId={locationId} data={data} today={day} />
      )}
    </Section>
  )
}

// --------------------------------------------------------------------------------------------- own rates

/** "Stawki" in the employee form: the person's own rate on each of their positions here, by day (e.g. for a longer
 * record). Saved at once, apart from the form's "Zapisz". */
export function OwnRates({
  employeeId,
  positionIds,
  locationId,
  today = new Date(),
}: {
  employeeId: string
  positionIds: string[]
  locationId: string
  today?: Date
}) {
  const { readOnly } = useManager()
  // Read only once the fold is open: most edits of a person are not about money.
  const [open, setOpen] = useState(false)
  const settings = usePaySettings(locationId, { query: { enabled: open } })
  const personal = usePersonalRates(locationId, { query: { enabled: open } })
  const save = useSetPersonalRate()
  const remove = useDeletePersonalRate()
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState<string | null>(null)
  const refresh = () => void queryClient.invalidateQueries()
  const day = toIsoDate(today)
  const data = settings.data?.data as PaySettingsOut | undefined
  const steps = ((personal.data?.data as PersonalRateOut[] | undefined) ?? []).filter((s) => s.employee_id === employeeId)
  const positions = (data?.positions ?? []).filter((p) => positionIds.includes(p.position_id))
  const own = positions.filter((p) => {
    const mine = steps.filter((s) => s.position_id === p.position_id)
    return stepOn(mine, day)?.hourly_rate != null || stepsAfter(mine, day).length > 0
  }).length
  if (positionIds.length === 0) return null

  return (
    <Disclosure
      boxed
      contentClassName="grid gap-3"
      onToggle={(event) => setOpen(event.currentTarget.open)}
      summary={
        <span className="flex flex-1 flex-wrap items-baseline justify-between gap-x-3 py-1">
          <span className="font-semibold">Stawki</span>
          {data && <span className="text-sm">{own ? `własna: ${own}` : 'jak stanowisko'}</span>}
        </span>
      }
    >
      <p className="m-0 text-sm text-ink-muted">
        Np. za dłuższy staż, bo stopień doświadczenia nie zmienia stawki. Zapisuje się od razu.
      </p>
      {!open ? null : settings.isPending || personal.isPending ? (
        <Loading>Wczytuję stawki…</Loading>
      ) : settings.isError || personal.isError ? (
        <ErrorState
          onRetry={() => {
            void settings.refetch()
            void personal.refetch()
          }}
        >
          {errorMessage(settings.error ?? personal.error, 'Nie udało się wczytać stawek. Spróbuj jeszcze raz.')}
        </ErrorState>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0">
          {positions.map((p) => {
            const position = stepOn(p.rates, day)?.hourly_rate
            return (
              <li key={p.position_id} className="grid gap-1">
                <b>{p.name}</b>
                <RateSteps
                  name={p.name}
                  steps={steps.filter((s) => s.position_id === p.position_id)}
                  fallback={position != null ? `stawka stanowiska, ${rateText(position)}` : 'stawka stanowiska (bez stawki)'}
                  emptyHint="Puste pole: znowu stawka stanowiska."
                  firstForAll={false}
                  today={day}
                  disabled={readOnly}
                  pending={save.isPending}
                  error={saving === p.position_id ? save.error : null}
                  onSave={(rate, done) => {
                    setSaving(p.position_id)
                    save.mutate(
                      { employeeId, data: { ...rate, position_id: p.position_id } },
                      { onSuccess: () => { done(); refresh() } },
                    )
                  }}
                  onDelete={(rateId) => remove.mutate({ rateId }, { onSuccess: refresh })}
                />
              </li>
            )
          })}
        </ul>
      )}
      {remove.isError && <InlineError>{errorMessage(remove.error, NETWORK_PROBLEM)}</InlineError>}
    </Disclosure>
  )
}

// --------------------------------------------------------------------------------------------- supplements

function daysText(days: number[]): string {
  const sorted = [...days].sort()
  if (sorted.length === 7) return 'codziennie'
  if (sorted.join() === '0,1,2,3,4') return 'pon–pt'
  if (sorted.join() === '5,6') return 'sob–niedz'
  return sorted.map((d) => WEEKDAY_HEADERS[d]).join(', ')
}

function valueText(kind: SupplementOutKind, value: number): string {
  return kind === 'percent' ? `+${value.toLocaleString('pl-PL')}% stawki` : `+${rateText(value)}`
}

function supplementWords(s: SupplementOut, names: Map<string, string>): string {
  const start = hhmm(s.start_time)
  const hours = start === hhmm(s.end_time) ? 'cała doba' : `${shortTime(start)}–${shortTime(hhmm(s.end_time))}`
  const positions = s.all_positions
    ? 'wszystkie stanowiska'
    : s.position_ids.map((id) => names.get(id) ?? 'stanowisko').join(', ')
  return [hours, daysText(s.weekdays), valueText(s.kind, s.value), positions].join(' · ')
}

function datesText(s: SupplementOut): string {
  return [s.valid_from && `od ${fullDay(s.valid_from)}`, s.valid_until && `do ${fullDay(s.valid_until)}`]
    .filter(Boolean)
    .join(' ')
}

function Supplements({ locationId, data, today }: { locationId: string; data: PaySettingsOut; today: string }) {
  const { readOnly } = useManager()
  const create = useCreateSupplement()
  const update = useUpdateSupplement()
  const end = useEndSupplement()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [ending, setEnding] = useState<SupplementOut | null>(null)
  const [endFrom, setEndFrom] = useState(today)
  const refresh = () => void queryClient.invalidateQueries()
  const names = new Map(data.positions.map((p) => [p.position_id, p.name]))
  const positions = data.positions.map((p) => ({ id: p.position_id, name: p.name }))
  const live = data.supplements.filter((s) => !s.valid_until || s.valid_until >= today)
  const ended = data.supplements.filter((s) => s.valid_until && s.valid_until < today)

  const item = (s: SupplementOut, canChange: boolean) => (
    <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2 last:border-b-0">
      {editing === s.id ? (
        <SupplementForm
          positions={positions}
          initial={s}
          today={today}
          pending={update.isPending}
          error={update.error}
          onCancel={() => setEditing(null)}
          onSubmit={(values, from) =>
            update.mutate(
              { supplementId: s.id, data: { ...values, change_from: from } },
              { onSuccess: () => { setEditing(null); refresh() } },
            )
          }
        />
      ) : (
        <>
          <span className="grid">
            <b>{s.name}</b>
            <span className="text-sm">{supplementWords(s, names)}</span>
            {datesText(s) && <span className="text-sm text-ink-muted">{datesText(s)}</span>}
          </span>
          {canChange && (
            <span className="flex gap-1">
              <Button
                variant="quiet"
                size="normal"
                disabled={readOnly}
                aria-label={`Zmień dodatek ${s.name}`}
                onClick={() => {
                  update.reset()
                  setEditing(s.id)
                }}
              >
                Zmień
              </Button>
              <Button
                variant="quiet"
                size="normal"
                disabled={readOnly}
                aria-label={`Zakończ dodatek ${s.name}`}
                onClick={() => {
                  end.reset()
                  setEndFrom(s.valid_from && s.valid_from > today ? s.valid_from : today)
                  setEnding(s)
                }}
              >
                Zakończ
              </Button>
            </span>
          )}
        </>
      )}
    </li>
  )

  return (
    <div className="grid gap-2">
      {live.length > 0 ? (
        <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
          {live.map((s) => item(s, true))}
        </ul>
      ) : (
        <p className="m-0 text-ink-muted">Lokal nie ma dodatków.</p>
      )}
      {ended.length > 0 && (
        <Disclosure summary={<span className="text-sm">{`Zakończone dodatki (${ended.length})`}</span>}>
          <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
            {ended.map((s) => item(s, false))}
          </ul>
        </Disclosure>
      )}
      {adding ? (
        <div className="rounded-md border border-line bg-surface p-4">
          <SupplementForm
            positions={positions}
            today={today}
            pending={create.isPending}
            error={create.error}
            onCancel={() => setAdding(false)}
            onSubmit={(values, from) =>
              create.mutate(
                { locationId, data: { ...values, valid_from: from } },
                { onSuccess: () => { setAdding(false); refresh() } },
              )
            }
          />
        </div>
      ) : (
        <div>
          <Button
            variant="secondary"
            size="normal"
            disabled={readOnly}
            onClick={() => {
              create.reset()
              setAdding(true)
            }}
          >
            <Plus aria-hidden="true" size={20} />
            Dodaj dodatek
          </Button>
        </div>
      )}
      <ConfirmSheet
        open={ending !== null}
        onOpenChange={(open) => !open && setEnding(null)}
        title={`Zakończyć dodatek „${ending?.name ?? ''}”?`}
        confirmLabel="Tak, zakończ dodatek"
        pending={end.isPending}
        error={end.error}
        onConfirm={() =>
          ending &&
          end.mutate(
            { supplementId: ending.id, params: { end_from: endFrom } },
            { onSuccess: () => { setEnding(null); refresh() } },
          )
        }
      >
        <p className="m-0">Zmiany przed tym dniem zachowają dodatek.</p>
        <TextField label="Bez dodatku od dnia" type="date" value={endFrom} onChange={(e) => setEndFrom(e.target.value)} required />
        {endFrom && inPastMonth(endFrom, today) && <PastMonthsNote />}
      </ConfirmSheet>
    </div>
  )
}

type SupplementValues = Omit<SupplementIn, 'valid_from'>

function SupplementForm({
  positions,
  initial,
  today,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  positions: Pick<PositionOut, 'id' | 'name'>[]
  initial?: SupplementOut
  today: string
  pending: boolean
  error: unknown
  /** `from`: the first day the new values count (a new supplement: null = for every shift). */
  onSubmit: (values: SupplementValues, from: string | null) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [start, setStart] = useState(initial ? hhmm(initial.start_time) : '22:00')
  const [end, setEnd] = useState(initial ? hhmm(initial.end_time) : '06:00')
  const [wholeDay, setWholeDay] = useState(initial ? hhmm(initial.start_time) === hhmm(initial.end_time) : false)
  const [days, setDays] = useState<number[]>(initial?.weekdays ?? [0, 1, 2, 3, 4, 5, 6])
  const [kind, setKind] = useState<SupplementOutKind>(initial?.kind ?? 'amount')
  const [value, setValue] = useState(() => {
    if (!initial) return ''
    return initial.kind === 'percent' ? initial.value.toLocaleString('pl-PL') : rateInput(initial.value)
  })
  const [all, setAll] = useState(initial?.all_positions ?? true)
  const [chosen, setChosen] = useState<string[]>(initial?.position_ids ?? [])
  const [from, setFrom] = useState(initial ? today : '')
  const [problem, setProblem] = useState<string | null>(null)
  const toggleDay = (day: number) => setDays((now) => (now.includes(day) ? now.filter((d) => d !== day) : [...now, day]))
  const togglePosition = (id: string) =>
    setChosen((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]))

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const amount = parseRate(value)
    if (days.length === 0) return setProblem('Wybierz co najmniej jeden dzień tygodnia.')
    if (amount === null || Number.isNaN(amount) || amount <= 0) {
      return setProblem(kind === 'percent' ? 'Wpisz procent, np. 20.' : 'Wpisz kwotę w złotych, np. 6,00.')
    }
    if (!all && chosen.length === 0) return setProblem('Wybierz stanowiska, których dotyczy dodatek.')
    setProblem(null)
    onSubmit(
      {
        name,
        start_time: wholeDay ? '00:00' : start,
        end_time: wholeDay ? '00:00' : end,
        weekdays: [...days].sort(),
        kind,
        value: amount,
        all_positions: all,
        position_ids: all ? [] : chosen,
      },
      from || null,
    )
  }

  return (
    <form onSubmit={submit} className="grid w-full gap-3">
      <TextField label="Nazwa" value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} placeholder="np. Noc" />
      <CheckField label="Cała doba" checked={wholeDay} onChange={(e) => setWholeDay(e.target.checked)} />
      {!wholeDay && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
          <TextField label="Od godziny" type="time" value={start} onChange={(e) => setStart(e.target.value)} required />
          <TextField label="Do godziny" type="time" value={end} onChange={(e) => setEnd(e.target.value)} required />
        </div>
      )}
      <fieldset className="m-0 grid gap-1 border-0 p-0">
        <legend className="mb-1 text-sm font-semibold">Dni</legend>
        <div className="flex flex-wrap gap-x-4">
          {WEEKDAY_HEADERS.map((label, day) => (
            <CheckField key={label} label={label} checked={days.includes(day)} onChange={() => toggleDay(day)} />
          ))}
        </div>
      </fieldset>
      <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
        <SelectField label="Dodatek" value={kind} onChange={(e) => setKind(e.target.value as SupplementOutKind)}>
          <option value="amount">zł za godzinę</option>
          <option value="percent">% stawki</option>
        </SelectField>
        <TextField
          label={kind === 'percent' ? 'Procent' : 'Kwota, zł/h'}
          inputMode="decimal"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required
          placeholder={kind === 'percent' ? 'np. 20' : 'np. 6,00'}
        />
      </div>
      <CheckField label="Wszystkie stanowiska" checked={all} onChange={(e) => setAll(e.target.checked)} />
      {!all && (
        <div className="flex flex-wrap gap-x-4">
          {positions.map((p) => (
            <CheckField key={p.id} label={p.name} checked={chosen.includes(p.id)} onChange={() => togglePosition(p.id)} />
          ))}
        </div>
      )}
      <TextField
        label={initial ? 'Zmiana od dnia' : 'Od dnia'}
        type="date"
        className="sm:max-w-xs"
        value={from}
        onChange={(e) => setFrom(e.target.value)}
        required={Boolean(initial)}
        hint={initial ? 'Wcześniejsze zmiany zachowają stary dodatek.' : 'Puste pole: dla wszystkich zmian, także minionych.'}
      />
      {from && inPastMonth(from, today) && <PastMonthsNote />}
      {problem && <InlineError>{problem}</InlineError>}
      {Boolean(error) && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="normal" disabled={pending}>
          {initial ? 'Zapisz dodatek' : 'Dodaj dodatek'}
        </Button>
        <Button variant="quiet" size="normal" onClick={onCancel}>
          Anuluj
        </Button>
      </div>
    </form>
  )
}

