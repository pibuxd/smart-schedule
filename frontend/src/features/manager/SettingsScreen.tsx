import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Moon, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type {
  LocationOut,
  LocationSetupOut,
  ShiftTypeIn,
  ShiftTypeOut,
  StaffingCellIn,
  StaffingExceptionOut,
} from '../../api/generated/model'
import {
  useCreatePosition,
  useCreateShiftType,
  useCreateStaffingException,
  useDeletePosition,
  useDeleteShiftType,
  useDeleteStaffingException,
  useLocationSetup,
  useSaveStaffing,
  useUpdatePosition,
  useUpdateShiftType,
} from '../../api/generated/staffing/staffing'
import { useLocationDetail, useUpdateLocation } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { CheckField, inputClass, Section, SelectField, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayTitle, parseDate, shortTime, WEEKDAY_HEADERS } from '../../lib/dates'
import { useManager } from './ManagerContext'

const hhmm = (value: string | null | undefined) => (value ? value.slice(0, 5) : '')

function shiftHours(st: { start_time: string | null; end_time: string | null }): string {
  if (!st.start_time || !st.end_time) return 'dowolne godziny'
  return `${shortTime(hhmm(st.start_time))}–${shortTime(hhmm(st.end_time))}`
}

const overnight = (st: { start_time: string | null; end_time: string | null }) =>
  Boolean(st.start_time && st.end_time && st.end_time < st.start_time)

export function LocationSettingsScreen({ locationId }: { locationId: string }) {
  const setup = useLocationSetup(locationId)
  const location = useLocationDetail(locationId)
  if (setup.isPending || location.isPending) return <Loading>Wczytuję ustawienia lokalu…</Loading>
  if (setup.isError || location.isError) {
    return (
      <ErrorState
        onRetry={() => {
          void setup.refetch()
          void location.refetch()
        }}
      >
        {errorMessage(setup.error ?? location.error, 'Nie udało się wczytać ustawień. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = setup.data.data as LocationSetupOut
  const info = location.data.data as LocationOut
  return (
    <div className="grid gap-10">
      <LocationForm location={info} />
      <div className="grid gap-10 lg:grid-cols-2">
        <PositionsSection locationId={locationId} setup={data} />
        <ShiftTypesSection locationId={locationId} setup={data} />
      </div>
      <StaffingSection key={JSON.stringify(data.staffing)} locationId={locationId} setup={data} />
      <ExceptionsSection locationId={locationId} setup={data} />
      <ArchiveSection location={info} />
    </div>
  )
}

// --------------------------------------------------------------------------------------------- location

function LocationForm({ location }: { location: LocationOut }) {
  const { readOnly } = useManager()
  const update = useUpdateLocation()
  const queryClient = useQueryClient()
  const [name, setName] = useState(location.name)
  const [address, setAddress] = useState(location.address)
  const [period, setPeriod] = useState(location.schedule_period)
  const [days, setDays] = useState(String(location.availability_deadline_days))
  const [saved, setSaved] = useState(false)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setSaved(false)
    update.mutate(
      {
        locationId: location.id,
        data: { name, address, schedule_period: period, availability_deadline_days: Number(days) },
      },
      {
        onSuccess: () => {
          setSaved(true)
          void queryClient.invalidateQueries()
        },
      },
    )
  }
  return (
    <Section title="Lokal">
      <form onSubmit={submit} className="grid gap-4 rounded-md border border-line bg-surface p-4 md:grid-cols-2 lg:grid-cols-4 lg:items-start">
        <TextField label="Nazwa" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        <TextField label="Adres" value={address} onChange={(e) => setAddress(e.target.value)} maxLength={300} />
        <SelectField label="Grafik układany na" value={period} onChange={(e) => setPeriod(e.target.value as 'week' | 'month')}>
          <option value="month">miesiąc</option>
          <option value="week">tydzień</option>
        </SelectField>
        <TextField
          label="Termin dyspozycji (dni przed okresem)"
          type="number"
          inputMode="numeric"
          min={0}
          max={60}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          hint="Podpowiedź przy nowym okresie. Dokładny dzień ustawisz przy każdym okresie."
        />
        <div className="flex flex-wrap items-center gap-3 md:col-span-2 lg:col-span-4">
          <Button type="submit" size="normal" disabled={update.isPending || readOnly}>
            Zapisz dane lokalu
          </Button>
          {saved && <span role="status" className="text-accent">Zapisane.</span>}
          {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
        </div>
      </form>
    </Section>
  )
}

function ArchiveSection({ location }: { location: LocationOut }) {
  const { role, readOnly } = useManager()
  const update = useUpdateLocation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  if (role !== 'owner' || location.archived) return null
  return (
    <Section
      title="Archiwum"
      description="Lokal, który przestał działać, przenieś do archiwum zamiast go usuwać: historia grafików i godzin zostaje."
    >
      <div>
        <Button variant="danger" size="normal" onClick={() => setOpen(true)} disabled={readOnly}>
          Przenieś lokal do archiwum
        </Button>
      </div>
      <Sheet open={open} onOpenChange={setOpen} title="Przenieść do archiwum?">
        <div className="grid gap-4">
          <p className="m-0">
            {location.name} zniknie z listy lokali i nie będzie można układać dla niego grafiku. Pracownicy zostaną,
            dawne grafiki też. Lokal przywrócisz jednym przyciskiem z listy lokali.
          </p>
          {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
          <Button
            variant="danger"
            wide
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                { locationId: location.id, data: { archived: true } },
                {
                  onSuccess: async () => {
                    await queryClient.invalidateQueries()
                    await navigate({ to: '/kierownik' })
                  },
                },
              )
            }
          >
            Tak, przenieś do archiwum
          </Button>
          <Button variant="secondary" wide onClick={() => setOpen(false)}>
            Zostaw
          </Button>
        </div>
      </Sheet>
    </Section>
  )
}

// --------------------------------------------------------------------------------------------- positions

function PositionsSection({ locationId, setup }: { locationId: string; setup: LocationSetupOut }) {
  const { readOnly } = useManager()
  const create = useCreatePosition()
  const rename = useUpdatePosition()
  const remove = useDeletePosition()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null)
  const refresh = () => void queryClient.invalidateQueries()
  const error = create.error ?? rename.error ?? remove.error

  return (
    <Section title="Stanowiska" description="Np. Sprzedawca, Piekarz, Kierownik zmiany.">
      <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
        {setup.positions.length === 0 && <li className="px-4 py-3 text-ink-muted">Nie ma jeszcze stanowisk.</li>}
        {setup.positions.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-1.5 last:border-b-0">
            {editing?.id === p.id ? (
              <form
                className="flex flex-1 flex-wrap items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  rename.mutate({ positionId: p.id, data: { name: editing.name } }, { onSuccess: () => { setEditing(null); refresh() } })
                }}
              >
                <TextField label="Nowa nazwa" className="flex-1" value={editing.name} onChange={(e) => setEditing({ id: p.id, name: e.target.value })} required />
                <Button type="submit" size="normal" disabled={rename.isPending}>
                  Zapisz
                </Button>
                <Button variant="quiet" size="normal" onClick={() => setEditing(null)}>
                  Anuluj
                </Button>
              </form>
            ) : (
              <>
                <span>
                  <b>{p.name}</b> <span className="text-sm text-ink-muted">({p.employees} os.)</span>
                </span>
                <span className="flex gap-1">
                  <Button variant="quiet" size="normal" disabled={readOnly} onClick={() => setEditing({ id: p.id, name: p.name })}>
                    Zmień nazwę
                  </Button>
                  <Button
                    variant="quiet"
                    size="normal"
                    aria-label={`Usuń stanowisko ${p.name}`}
                    disabled={readOnly || remove.isPending}
                    onClick={() => remove.mutate({ positionId: p.id }, { onSuccess: refresh })}
                  >
                    <Trash2 aria-hidden="true" size={18} />
                    Usuń
                  </Button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate({ locationId, data: { name } }, { onSuccess: () => { setName(''); refresh() } })
        }}
      >
        <TextField label="Nowe stanowisko" className="min-w-48 flex-1" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
        <Button type="submit" variant="secondary" size="normal" disabled={create.isPending || readOnly}>
          <Plus aria-hidden="true" size={20} />
          Dodaj
        </Button>
      </form>
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
    </Section>
  )
}

// --------------------------------------------------------------------------------------------- shift types

function ShiftTypesSection({ locationId, setup }: { locationId: string; setup: LocationSetupOut }) {
  const { readOnly } = useManager()
  const [editing, setEditing] = useState<ShiftTypeOut | 'new' | null>(null)
  return (
    <Section
      title="Zmiany i godziny"
      description="Godziny końca wcześniejsze niż początek znaczą zmianę do rana (np. 22–6)."
      action={
        <Button variant="secondary" size="normal" onClick={() => setEditing('new')} disabled={readOnly}>
          <Plus aria-hidden="true" size={20} />
          Nowa zmiana
        </Button>
      }
    >
      <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
        {setup.shift_types.length === 0 && <li className="px-4 py-3 text-ink-muted">Nie ma jeszcze zmian.</li>}
        {setup.shift_types.map((st) => (
          <li key={st.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-1.5 last:border-b-0">
            <span className="flex flex-wrap items-center gap-2">
              <b>{st.name}</b>
              <span className="tabular-nums">{shiftHours(st)}</span>
              {overnight(st) && (
                <Tag>
                  <Moon aria-hidden="true" size={14} />
                  do rana
                </Tag>
              )}
              {st.is_closing && <Tag>zamykająca</Tag>}
            </span>
            <Button variant="quiet" size="normal" onClick={() => setEditing(st)} disabled={readOnly}>
              Zmień
            </Button>
          </li>
        ))}
      </ul>
      <Sheet
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        title={editing === 'new' ? 'Nowa zmiana' : (editing?.name ?? '')}
      >
        {editing !== null && (
          <ShiftTypeForm
            key={editing === 'new' ? 'new' : editing.id}
            locationId={locationId}
            shiftType={editing === 'new' ? null : editing}
            onDone={() => setEditing(null)}
          />
        )}
      </Sheet>
    </Section>
  )
}

function ShiftTypeForm({
  locationId,
  shiftType,
  onDone,
}: {
  locationId: string
  shiftType: ShiftTypeOut | null
  onDone: () => void
}) {
  const create = useCreateShiftType()
  const update = useUpdateShiftType()
  const remove = useDeleteShiftType()
  const queryClient = useQueryClient()
  const [name, setName] = useState(shiftType?.name ?? '')
  const [kind, setKind] = useState<'fixed' | 'flexible'>(shiftType?.kind ?? 'fixed')
  const [start, setStart] = useState(hhmm(shiftType?.start_time))
  const [end, setEnd] = useState(hhmm(shiftType?.end_time))
  const [closing, setClosing] = useState(shiftType?.is_closing ?? false)
  const done = () => {
    void queryClient.invalidateQueries()
    onDone()
  }
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const data: ShiftTypeIn = {
      name,
      kind,
      start_time: start || null,
      end_time: end || null,
      is_closing: closing,
    }
    if (shiftType) update.mutate({ shiftTypeId: shiftType.id, data }, { onSuccess: done })
    else create.mutate({ locationId, data }, { onSuccess: done })
  }
  const error = create.error ?? update.error ?? remove.error
  const night = start && end && end < start
  return (
    <form onSubmit={submit} className="grid gap-4">
      <TextField label="Nazwa" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} placeholder="np. Ranna" />
      <fieldset className="m-0 grid gap-1 border-0 p-0">
        <legend className="mb-1 font-semibold">Godziny</legend>
        <label className="flex min-h-(--touch) cursor-pointer items-center gap-3">
          <input type="radio" name="kind" className="size-6 accent-accent" checked={kind === 'fixed'} onChange={() => setKind('fixed')} />
          Stałe godziny
        </label>
        <label className="flex min-h-(--touch) cursor-pointer items-center gap-3">
          <input type="radio" name="kind" className="size-6 accent-accent" checked={kind === 'flexible'} onChange={() => setKind('flexible')} />
          Dowolne godziny (ustawisz je w obsadzie, np. dostawa)
        </label>
      </fieldset>
      <div className="grid grid-cols-2 gap-4">
        <TextField label="Od" type="time" value={start} onChange={(e) => setStart(e.target.value)} required={kind === 'fixed'} />
        <TextField label="Do" type="time" value={end} onChange={(e) => setEnd(e.target.value)} required={kind === 'fixed'} />
      </div>
      {night && <p className="m-0 text-sm text-ink-muted">Ta zmiana kończy się następnego dnia rano.</p>}
      <CheckField
        label="Zmiana zamykająca"
        hint="Liczy się do równego podziału zamknięć."
        checked={closing}
        onChange={(e) => setClosing(e.target.checked)}
      />
      {shiftType && (
        <p className="m-0 text-sm text-ink-muted">Nowe godziny dotyczą grafików układanych od teraz. Ułożone grafiki zostają bez zmian.</p>
      )}
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={create.isPending || update.isPending}>
        Zapisz zmianę
      </Button>
      {shiftType && (
        <Button
          variant="danger"
          wide
          disabled={remove.isPending}
          onClick={() => remove.mutate({ shiftTypeId: shiftType.id }, { onSuccess: done })}
        >
          <Trash2 aria-hidden="true" size={18} />
          Usuń tę zmianę (razem z jej obsadą)
        </Button>
      )}
    </form>
  )
}

// --------------------------------------------------------------------------------------------- staffing

type Counts = Record<string, string>
type Hours = Record<string, { start: string; end: string }>
const cellKey = (st: string, pos: string, day: number) => `${st}|${pos}|${day}`
const rowKey = (st: string, pos: string) => `${st}|${pos}`

/** The weekly table: for every shift and position, how many people each weekday needs. */
function StaffingSection({ locationId, setup }: { locationId: string; setup: LocationSetupOut }) {
  const { readOnly } = useManager()
  const save = useSaveStaffing()
  const queryClient = useQueryClient()
  const [counts, setCounts] = useState<Counts>(() => {
    const result: Counts = {}
    for (const c of setup.staffing) result[cellKey(c.shift_type_id, c.position_id, c.weekday)] = String(c.count)
    return result
  })
  const [hours, setHours] = useState<Hours>(() => {
    const result: Hours = {}
    for (const c of setup.staffing) {
      if (c.start_time && c.end_time) result[rowKey(c.shift_type_id, c.position_id)] = { start: hhmm(c.start_time), end: hhmm(c.end_time) }
    }
    return result
  })
  const [saved, setSaved] = useState(false)

  if (setup.shift_types.length === 0 || setup.positions.length === 0) {
    return (
      <Section title="Obsada">
        <EmptyState title="Najpierw stanowiska i zmiany">
          <p className="m-0">Dodaj wyżej co najmniej jedno stanowisko i jedną zmianę. Wtedy ustawisz tu, ilu ludzi potrzeba.</p>
        </EmptyState>
      </Section>
    )
  }

  const set = (key: string, value: string) => {
    setSaved(false)
    setCounts((now) => ({ ...now, [key]: value }))
  }
  const copyMonday = (st: string, pos: string) => {
    setSaved(false)
    setCounts((now) => {
      const next = { ...now }
      for (let d = 1; d < 7; d++) next[cellKey(st, pos, d)] = now[cellKey(st, pos, 0)] ?? ''
      return next
    })
  }
  const submit = () => {
    const cells: StaffingCellIn[] = []
    for (const st of setup.shift_types) {
      for (const pos of setup.positions) {
        const flex = st.kind === 'flexible' ? hours[rowKey(st.id, pos.id)] : undefined
        for (let d = 0; d < 7; d++) {
          const count = Number(counts[cellKey(st.id, pos.id, d)] || 0)
          if (!count) continue
          cells.push({
            weekday: d,
            shift_type_id: st.id,
            position_id: pos.id,
            count,
            start_time: flex?.start || null,
            end_time: flex?.end || null,
          })
        }
      }
    }
    save.mutate(
      { locationId, data: { cells } },
      {
        onSuccess: () => {
          setSaved(true)
          void queryClient.invalidateQueries()
        },
      },
    )
  }

  return (
    <Section
      title="Obsada"
      description="Ilu ludzi z danym stanowiskiem potrzeba na każdej zmianie w każdy dzień tygodnia. Puste pole = nikt."
    >
      <div className="overflow-x-auto rounded-md border border-line bg-surface" tabIndex={0} aria-label="Tabela obsady">
        <table className="w-full border-separate border-spacing-0">
          <caption className="sr-only">Obsada: zmiana i stanowisko w wierszach, dni tygodnia w kolumnach</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 z-10 min-w-48 border-b border-line bg-surface px-3 py-2 text-left">
                Zmiana i stanowisko
              </th>
              {WEEKDAY_HEADERS.map((d, i) => (
                <th key={d} scope="col" className={`border-b border-line px-1 py-2 text-center ${i >= 5 ? 'bg-grid' : ''}`}>
                  {d}
                </th>
              ))}
              <th scope="col" className="border-b border-line px-2 py-2">
                <span className="sr-only">Skróty</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {setup.shift_types.map((st) =>
              setup.positions.map((pos, index) => (
                <tr key={rowKey(st.id, pos.id)}>
                  <th scope="row" className={`sticky left-0 z-10 bg-surface px-3 py-1.5 text-left font-normal ${index === setup.positions.length - 1 ? 'border-b-2 border-ink' : 'border-b border-line'}`}>
                    <span className="block font-semibold">
                      {st.name} <span className="font-normal text-ink-muted tabular-nums">{shiftHours(st)}</span>
                    </span>
                    <span className="block text-sm">{pos.name}</span>
                    {st.kind === 'flexible' && (
                      <span className="mt-1 flex items-center gap-1 text-sm">
                        <input
                          type="time"
                          aria-label={`${st.name}, ${pos.name}: od`}
                          className={`${inputClass} w-28`}
                          value={hours[rowKey(st.id, pos.id)]?.start ?? ''}
                          onChange={(e) => setHours((h) => ({ ...h, [rowKey(st.id, pos.id)]: { start: e.target.value, end: h[rowKey(st.id, pos.id)]?.end ?? '' } }))}
                        />
                        –
                        <input
                          type="time"
                          aria-label={`${st.name}, ${pos.name}: do`}
                          className={`${inputClass} w-28`}
                          value={hours[rowKey(st.id, pos.id)]?.end ?? ''}
                          onChange={(e) => setHours((h) => ({ ...h, [rowKey(st.id, pos.id)]: { start: h[rowKey(st.id, pos.id)]?.start ?? '', end: e.target.value } }))}
                        />
                      </span>
                    )}
                  </th>
                  {WEEKDAY_HEADERS.map((d, i) => (
                    <td key={d} className={`px-1 py-1.5 text-center ${i >= 5 ? 'bg-grid' : ''} ${index === setup.positions.length - 1 ? 'border-b-2 border-ink' : 'border-b border-line'}`}>
                      <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={50}
                        aria-label={`${st.name}, ${pos.name}, ${d}`}
                        className={`${inputClass} w-14 px-1 text-center tabular-nums`}
                        value={counts[cellKey(st.id, pos.id, i)] ?? ''}
                        onChange={(e) => set(cellKey(st.id, pos.id, i), e.target.value)}
                        disabled={readOnly}
                      />
                    </td>
                  ))}
                  <td className={`px-2 py-1.5 ${index === setup.positions.length - 1 ? 'border-b-2 border-ink' : 'border-b border-line'}`}>
                    <Button variant="quiet" size="normal" className="px-2 text-sm whitespace-nowrap" onClick={() => copyMonday(st.id, pos.id)} disabled={readOnly}>
                      Cały tydzień jak pon.
                    </Button>
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={submit} disabled={save.isPending || readOnly}>
          Zapisz obsadę
        </Button>
        {saved && <span role="status" className="text-accent">Obsada zapisana.</span>}
        {save.isError && <InlineError>{errorMessage(save.error, NETWORK_PROBLEM)}</InlineError>}
      </div>
    </Section>
  )
}

// --------------------------------------------------------------------------------------------- exceptions

function ExceptionsSection({ locationId, setup }: { locationId: string; setup: LocationSetupOut }) {
  const { readOnly } = useManager()
  const create = useCreateStaffingException()
  const remove = useDeleteStaffingException()
  const queryClient = useQueryClient()
  const [date, setDate] = useState('')
  const [shift, setShift] = useState(setup.shift_types[0]?.id ?? '')
  const [position, setPosition] = useState(setup.positions[0]?.id ?? '')
  const [count, setCount] = useState('0')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [note, setNote] = useState('')
  const shiftName = new Map(setup.shift_types.map((s) => [s.id, s.name]))
  const positionName = new Map(setup.positions.map((p) => [p.id, p.name]))
  const refresh = () => void queryClient.invalidateQueries()

  if (setup.shift_types.length === 0 || setup.positions.length === 0) return null

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(
      {
        locationId,
        data: {
          date,
          shift_type_id: shift,
          position_id: position,
          count: Number(count),
          start_time: start || null,
          end_time: end || null,
          note,
        },
      },
      {
        onSuccess: () => {
          setNote('')
          setStart('')
          setEnd('')
          refresh()
        },
      },
    )
  }
  const describe = (e: StaffingExceptionOut) => {
    const who = `${shiftName.get(e.shift_type_id) ?? 'Zmiana'}, ${positionName.get(e.position_id) ?? 'stanowisko'}`
    const what = e.count === 0 ? 'nikt' : `${e.count} os.`
    const hours = e.start_time && e.end_time ? `, ${shortTime(hhmm(e.start_time))}–${shortTime(hhmm(e.end_time))}` : ''
    return `${who}: ${what}${hours}`
  }

  return (
    <Section
      title="Wyjątki w obsadzie"
      description="Inna obsada w jeden dzień, np. Wigilia albo dzień zamknięcia (0 osób). Zastępuje zwykłą obsadę tego dnia."
    >
      {setup.exceptions.length > 0 && (
        <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
          {setup.exceptions.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-1.5 last:border-b-0">
              <span>
                <b>{dayTitle(parseDate(e.date))}</b> · {describe(e)}
                {e.note && <span className="text-ink-muted"> ({e.note})</span>}
              </span>
              <Button variant="quiet" size="normal" disabled={readOnly || remove.isPending} onClick={() => remove.mutate({ exceptionId: e.id }, { onSuccess: refresh })}>
                Usuń
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="grid gap-4 rounded-md border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-start">
        <TextField label="Dzień" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        <SelectField label="Zmiana" value={shift} onChange={(e) => setShift(e.target.value)}>
          {setup.shift_types.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </SelectField>
        <SelectField label="Stanowisko" value={position} onChange={(e) => setPosition(e.target.value)}>
          {setup.positions.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </SelectField>
        <TextField label="Liczba osób" type="number" inputMode="numeric" min={0} max={50} value={count} onChange={(e) => setCount(e.target.value)} required />
        <TextField label="Inne godziny: od (nieobowiązkowo)" type="time" value={start} onChange={(e) => setStart(e.target.value)} />
        <TextField label="do" type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
        <TextField label="Powód (nieobowiązkowo)" className="sm:col-span-2" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="np. Wigilia" />
        <div className="grid gap-2 sm:col-span-2 lg:col-span-4">
          {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
          <div>
            <Button type="submit" variant="secondary" size="normal" disabled={create.isPending || readOnly}>
              <Plus aria-hidden="true" size={20} />
              Dodaj wyjątek
            </Button>
          </div>
        </div>
      </form>
    </Section>
  )
}
