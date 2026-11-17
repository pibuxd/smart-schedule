import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Moon, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type {
  LocationOut,
  LocationSetupOut,
  ManagerOverviewOut,
  ShiftTypeIn,
  ShiftTypeOut,
  StaffingCellIn,
  StaffingExceptionOut,
} from '../../api/generated/model'
import {
  useCreateClosure,
  useCreatePosition,
  useCreateShiftType,
  useCreateStaffingException,
  useDeleteClosure,
  useDeletePosition,
  useDeleteShiftType,
  useDeleteStaffingException,
  useLocationSetup,
  useSaveStaffing,
  useUpdatePosition,
  useUpdateShiftType,
} from '../../api/generated/staffing/staffing'
import { useManagerOverview, useLocationDetail, useUpdateLocation } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { CheckField, Section, SelectField, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayTitle, parseDate, shortTime, spanHours, WEEKDAY_HEADERS } from '../../lib/dates'
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
    <div className="grid min-w-0 grid-cols-1 gap-10">
      <LocationForm key={info.id} location={info} />
      <div className="grid min-w-0 grid-cols-1 gap-10 lg:grid-cols-2">
        <PositionsSection locationId={locationId} setup={data} />
        <ShiftTypesSection locationId={locationId} setup={data} />
      </div>
      <StaffingSection key={JSON.stringify(data.staffing)} locationId={locationId} setup={data} />
      <ClosuresSection locationId={locationId} setup={data} />
      <ExceptionsSection locationId={locationId} setup={data} />
      <ArchiveSection location={info} />
    </div>
  )
}

// --------------------------------------------------------------------------------------------- location

function LocationForm({ location }: { location: LocationOut }) {
  const { readOnly, role, companyId } = useManager()
  const overview = useManagerOverview({ company_id: companyId }, { query: { enabled: role === 'owner' } })
  const groups = (overview.data?.data as ManagerOverviewOut | undefined)?.groups ?? []
  const [groupId, setGroupId] = useState(location.group_id ?? '')
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
        data: {
          name, address, schedule_period: period, availability_deadline_days: Number(days),
          ...(role === 'owner' && groupId !== (location.group_id ?? '') ? { group_id: groupId || null } : {}),
        },
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
        {role === 'owner' && groups.length > 0 && (
          <SelectField label="Grupa lokali" value={groupId} disabled={readOnly} onChange={(e) => setGroupId(e.target.value)}
            hint={groupId === (location.group_id ?? '') ? undefined : groupId
              ? 'Po zapisaniu lokal będzie korzystać z zasad wybranej grupy. Własne ustawienia lokalu nadal mają pierwszeństwo.'
              : 'Po zapisaniu przestaną obowiązywać zasady dziedziczone z grupy. Zostaną zasady ustawione w tym lokalu.'}>
            <option value="">Bez grupy</option>
            {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </SelectField>
        )}
        <TextField label="Adres" value={address} onChange={(e) => setAddress(e.target.value)} maxLength={300} />
        <SelectField label="Grafik układasz na" value={period} onChange={(e) => setPeriod(e.target.value as 'week' | 'month')}>
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
          hint="Tak podpowiemy termin przy nowym grafiku. Dokładny dzień ustawisz za każdym razem."
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
      description="Lokal, który już nie działa, przenieś do archiwum. Dawne grafiki i godziny zostaną."
    >
      <div>
        <Button variant="danger" size="normal" onClick={() => setOpen(true)} disabled={readOnly}>
          Przenieś lokal do archiwum
        </Button>
      </div>
      <Sheet open={open} onOpenChange={setOpen} title="Przenieść do archiwum?">
        <div className="grid gap-4">
          <p className="m-0">
            {location.name} zniknie z listy lokali i nie ułożysz dla niego grafiku. Pracownicy i dawne grafiki
            zostaną. Lokal przywrócisz jednym przyciskiem na liście lokali.
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
    <Section title="Stanowiska" description="Np. Sprzedawca, Kelner, Kucharz, Kierownik zmiany.">
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
      description="Gdy koniec jest wcześniej niż początek, zmiana trwa do rana (np. 22–6)."
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
    if (tooLong) return
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
  const length = start && end ? spanHours(start, end) : 0
  // A 23-hour shift is more likely a typo than a plan: ask once before saving.
  const [longConfirmed, setLongConfirmed] = useState(false)
  const tooLong = kind === 'fixed' && length > 12 && !longConfirmed
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
      {night && !(kind === 'fixed' && length > 12) && (
        <p className="m-0 text-sm text-ink-muted">Ta zmiana kończy się następnego dnia rano.</p>
      )}
      {kind === 'fixed' && length > 12 && (
        <CheckField
          label={`Tak, ta zmiana trwa ${String(length).replace('.', ',')} godz.`}
          hint={night ? 'Kończy się następnego dnia. Sprawdź, czy godziny nie są zamienione.' : 'Sprawdź, czy godziny są dobre.'}
          checked={longConfirmed}
          onChange={(e) => setLongConfirmed(e.target.checked)}
        />
      )}
      <CheckField
        label="Zmiana zamykająca"
        hint="Zamknięcia lokalu dzielimy po równo między pracowników."
        checked={closing}
        onChange={(e) => setClosing(e.target.checked)}
      />
      {shiftType && (
        <p className="m-0 text-sm text-ink-muted">Nowe godziny działają w grafikach, które ułożysz od teraz. Gotowe grafiki się nie zmienią.</p>
      )}
      {error && <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={create.isPending || update.isPending || tooLong}>
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

type StaffingValues = { count: string; experienced: string; start: string; end: string }
const emptyStaffing: StaffingValues = { count: '', experienced: '', start: '', end: '' }
const cellKey = (shift: string, position: string, day: number) => `${shift}|${position}|${day}`

function StaffingSection({ locationId, setup }: { locationId: string; setup: LocationSetupOut }) {
  const { readOnly } = useManager()
  const save = useSaveStaffing()
  const queryClient = useQueryClient()
  const [cells, setCells] = useState<Record<string, StaffingValues>>(() => Object.fromEntries(
    setup.staffing.map((c) => [cellKey(c.shift_type_id, c.position_id, c.weekday), {
      count: String(c.count), experienced: String(c.experienced), start: c.start_time ?? '', end: c.end_time ?? '',
    }]),
  ))
  const [saved, setSaved] = useState(false)

  if (!setup.shift_types.length || !setup.positions.length) {
    return (
      <Section title="Obsada">
        <EmptyState title="Najpierw stanowiska i zmiany">
          <p className="m-0">Najpierw dodaj wyżej stanowisko i zmianę. Wtedy ustawisz tu, ile osób potrzeba.</p>
        </EmptyState>
      </Section>
    )
  }

  function change(key: string, field: keyof StaffingValues, value: string) {
    setSaved(false)
    setCells((now) => ({ ...now, [key]: { ...(now[key] ?? emptyStaffing), [field]: value } }))
  }

  function copyMonday(shift: string, position: string) {
    setSaved(false)
    setCells((now) => {
      const next = { ...now }
      const monday = now[cellKey(shift, position, 0)] ?? emptyStaffing
      for (let day = 1; day < 7; day++) next[cellKey(shift, position, day)] = monday
      return next
    })
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const values: StaffingCellIn[] = []
    for (const st of setup.shift_types) {
      for (const pos of setup.positions) {
        WEEKDAY_HEADERS.forEach((_, day) => {
          const cell = cells[cellKey(st.id, pos.id, day)]
          if (!Number(cell?.count)) return
          values.push({
            weekday: day, shift_type_id: st.id, position_id: pos.id,
            count: Number(cell.count), experienced: Number(cell.experienced),
            start_time: cell.start || null, end_time: cell.end || null,
          })
        })
      }
    }
    save.mutate({ locationId, data: { cells: values } }, { onSuccess: () => {
      setSaved(true)
      void queryClient.invalidateQueries()
    } })
  }

  return (
    <Section title="Obsada" description="Wpisz, ile osób potrzeba każdego dnia i ile z nich musi mieć doświadczenie na tym stanowisku. Puste pole oznacza zero osób.">
      <form onSubmit={submit} className="grid min-w-0 gap-4">
        {setup.shift_types.flatMap((st) => setup.positions.map((pos) => (
          <fieldset key={cellKey(st.id, pos.id, 0)} disabled={readOnly || save.isPending} className="min-w-0 rounded-md border border-line bg-surface p-3">
            <legend className="px-1 font-bold">{st.name} · {pos.name} ({shiftHours(st)})</legend>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
              {WEEKDAY_HEADERS.map((day, i) => {
                const key = cellKey(st.id, pos.id, i)
                const cell = cells[key] ?? emptyStaffing
                const label = `${st.name}, ${pos.name}, ${day}`
                return (
                  <fieldset key={day} className="grid min-w-0 content-start gap-1 border-0 p-0">
                    <legend className="font-bold">{day}</legend>
                    <TextField label="Osoby" aria-label={label} type="number" min={0} max={50} placeholder="0"
                      value={cell.count} onChange={(e) => change(key, 'count', e.target.value)} />
                    <TextField label="W tym doświadczonych" aria-label={`${label}: w tym doświadczonych`} type="number"
                      min={0} max={Number(cell.count) || 0} placeholder="0" disabled={!Number(cell.count)}
                      value={cell.experienced} onChange={(e) => change(key, 'experienced', e.target.value)} />
                    {st.kind === 'flexible' && (<>
                      <TextField label="Od" aria-label={`${label}: od`} type="time" step="any" value={cell.start}
                        onChange={(e) => change(key, 'start', e.target.value)} />
                      <TextField label="Do" aria-label={`${label}: do`} type="time" step="any" value={cell.end}
                        onChange={(e) => change(key, 'end', e.target.value)} />
                      {Number(cell.count) > 0 && (!(cell.start || st.start_time) || !(cell.end || st.end_time)) && (
                        <p className="m-0 text-sm font-semibold text-prefer-not">
                          Uzupełnij początek i koniec zmiany przed ułożeniem grafiku na ten dzień.
                        </p>
                      )}
                    </>)}
                  </fieldset>
                )
              })}
            </div>
            <Button type="button" variant="quiet" size="normal" onClick={() => copyMonday(st.id, pos.id)}>Cały tydzień jak pon.</Button>
          </fieldset>
        )))}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={save.isPending || readOnly}>Zapisz obsadę</Button>
          {saved && <span role="status" className="text-accent">Obsada zapisana.</span>}
          {save.isError && <InlineError>{errorMessage(save.error, NETWORK_PROBLEM)}</InlineError>}
        </div>
      </form>
    </Section>
  )
}

// --------------------------------------------------------------------------------------------- closed days

function ClosuresSection({ locationId, setup }: { locationId: string; setup: LocationSetupOut }) {
  const { readOnly } = useManager()
  const create = useCreateClosure()
  const remove = useDeleteClosure()
  const queryClient = useQueryClient()
  const [date, setDate] = useState('')
  const [note, setNote] = useState('')
  const refresh = () => void queryClient.invalidateQueries()

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(
      { locationId, data: { date, note } },
      {
        onSuccess: () => {
          setDate('')
          setNote('')
          refresh()
        },
      },
    )
  }

  return (
    <Section
      title="Dni zamknięcia"
      description="Dni, w które lokal jest zamknięty, np. święta albo remont. Tego dnia nikt nie dostanie zmiany w tym lokalu."
    >
      {setup.closures.length > 0 ? (
        <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
          {setup.closures.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-1.5 last:border-b-0">
              <span>
                <b>{dayTitle(parseDate(c.date))}</b>
                {c.note && <span className="text-ink-muted"> ({c.note})</span>}
                {(c.in_draft || c.in_published) && (
                  <span className="block text-sm text-ink-muted">
                    {c.in_published ? 'Opublikowany grafik' : 'Szkic grafiku'} ma jeszcze zmiany w ten dzień. Ułóż grafik
                    od nowa{c.in_published ? ' i opublikuj go' : ''}, żeby zniknęły. Ułożenie od nowa zostawia tylko
                    przypięte zmiany, inne ręczne poprawki znikną.
                  </span>
                )}
              </span>
              <Button variant="quiet" size="normal" disabled={readOnly || remove.isPending} onClick={() => remove.mutate({ closureId: c.id }, { onSuccess: refresh })}>
                Usuń
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-ink-muted">Lokal nie ma zaplanowanych dni zamknięcia.</p>
      )}
      <form onSubmit={submit} className="grid gap-4 rounded-md border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-start">
        <TextField label="Dzień" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        <TextField label="Powód (nieobowiązkowo)" className="sm:col-span-2" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="np. Boże Narodzenie" />
        <div className="grid gap-2 sm:col-span-2 lg:col-span-4">
          {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
          {remove.isError && <InlineError>{errorMessage(remove.error, NETWORK_PROBLEM)}</InlineError>}
          <div>
            <Button type="submit" variant="secondary" size="normal" disabled={create.isPending || readOnly}>
              <Plus aria-hidden="true" size={20} />
              Dodaj dzień zamknięcia
            </Button>
          </div>
        </div>
      </form>
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
  const [experiencedCount, setExperiencedCount] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [note, setNote] = useState('')
  const shiftName = new Map(setup.shift_types.map((s) => [s.id, s.name]))
  const positionName = new Map(setup.positions.map((p) => [p.id, p.name]))
  const refresh = () => void queryClient.invalidateQueries()

  if (setup.shift_types.length === 0 || setup.positions.length === 0) return null

  // Left empty, the exception keeps what the weekday usually asks for, so the requirement does not vanish
  // on the very day the manager adds more people.
  const weekday = date ? (parseDate(date).getDay() + 6) % 7 : null
  const usual =
    setup.staffing.find((c) => c.weekday === weekday && c.shift_type_id === shift && c.position_id === position)
      ?.experienced ?? 0
  const experiencedNow = experiencedCount === '' ? Math.min(Number(count), usual) : Number(experiencedCount)

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
          experienced: experiencedNow,
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
    const what = e.count === 0 ? 'nikt' : `${e.count} os.${e.experienced ? `, w tym ${e.experienced} dośw.` : ''}`
    const hours = e.start_time && e.end_time ? `, ${shortTime(hhmm(e.start_time))}–${shortTime(hhmm(e.end_time))}` : ''
    return `${who}: ${what}${hours}`
  }

  return (
    <Section
      title="Wyjątki w obsadzie"
      description="Inna obsada w wybrany dzień, np. w Wigilię. Zastępuje zwykłą obsadę tego dnia. Gdy lokal jest zamknięty cały dzień, dodaj go wyżej, w dniach zamknięcia."
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
        <TextField label="W tym doświadczonych" type="number" inputMode="numeric" min={0} max={50} placeholder={String(experiencedNow)} value={experiencedCount} onChange={(e) => setExperiencedCount(e.target.value)} hint={usual > 0 ? `Puste = jak zwykle w ten dzień (${experiencedNow}).` : undefined} />
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
