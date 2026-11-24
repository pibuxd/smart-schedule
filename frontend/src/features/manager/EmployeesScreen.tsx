import { useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'

import type { EmployeeIn, EmployeeOut, InvitationOut, LocationSetupOut, MeOut, PositionOut } from '../../api/generated/model'
import { useMe } from '../../api/generated/auth/auth'
import {
  useAddMyselfAsEmployee,
  useLocationEmployees,
  useLocationSetup,
  useRemoveEmployee,
  useUpdateEmployee,
} from '../../api/generated/staffing/staffing'
import { useCancelInvitation, useInviteToLocation, useLocationInvitations } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { CheckField, Section, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, errorStatus, NETWORK_PROBLEM } from '../../lib/api-error'
import { prettyPhone } from '../auth/phone'
import { InviteManyButton } from './InviteMany'
import { useManager } from './ManagerContext'
import { OwnRates } from './PayRates'
import { EXPERIENCE, shifts } from './words'

export function EmployeesScreen({ locationId }: { locationId: string }) {
  const employees = useLocationEmployees(locationId)
  const setup = useLocationSetup(locationId)
  const [editing, setEditing] = useState<EmployeeOut | null>(null)

  if (employees.isPending || setup.isPending) return <Loading>Wczytuję pracowników…</Loading>
  if (employees.isError || setup.isError) {
    return (
      <ErrorState
        onRetry={() => {
          void employees.refetch()
          void setup.refetch()
        }}
      >
        {errorMessage(employees.error ?? setup.error, 'Nie udało się wczytać pracowników. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const list = employees.data.data as EmployeeOut[]
  const positions = (setup.data.data as LocationSetupOut).positions
  const names = new Map(positions.map((p) => [p.id, p.name]))
  const active = list.filter((e) => e.is_active)
  const off = list.filter((e) => !e.is_active)

  return (
    <div className="grid gap-8">
      <Section
        title={`W grafiku (${active.length})`}
        description="Doświadczenie widzisz tylko Ty. Cel i maksimum godzin to wskazówki dla grafiku."
      >
        {active.length === 0 ? (
          <EmptyState title="Nikt jeszcze nie pracuje w tym lokalu">
            <p className="m-0">Zaproś pierwszą osobę niżej. Wystarczy numer telefonu.</p>
          </EmptyState>
        ) : (
          <EmployeeList employees={active} names={names} onEdit={setEditing} />
        )}
        <AddMyself locationId={locationId} employees={list} />
      </Section>

      <InvitationsSection locationId={locationId} positions={positions} />

      {off.length > 0 && (
        <Section
          title={`Wyłączeni z grafiku (${off.length})`}
          description="Nie dostają nowych zmian. Możesz ich włączyć z powrotem."
        >
          <EmployeeList employees={off} names={names} onEdit={setEditing} />
        </Section>
      )}

      <Sheet
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        title={editing ? `${editing.first_name} ${editing.last_name}`.trim() || 'Pracownik' : ''}
      >
        {editing && (
          <EmployeeForm
            key={editing.id}
            employee={editing}
            positions={positions}
            locationId={locationId}
            onDone={() => setEditing(null)}
          />
        )}
      </Sheet>
    </div>
  )
}

/**
 * A manager who also works shifts adds themselves with one button (no invitation to their own number).
 * Shown only while the manager is not on this location's list.
 */
function AddMyself({ locationId, employees }: { locationId: string; employees: EmployeeOut[] }) {
  const { readOnly } = useManager()
  const queryClient = useQueryClient()
  const me = useMe({ query: { retry: false, staleTime: 60_000 } })
  const add = useAddMyselfAsEmployee()
  const phone = me.data?.status === 200 ? (me.data.data as MeOut).phone : null
  if (!phone || employees.some((e) => e.phone === phone && e.is_active)) return null
  return (
    <div className="grid gap-2 rounded-md border border-dashed border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <span>
          <b>Też pracujesz na zmianach?</b>
          <span className="block text-sm text-ink-muted">
            Dodaj siebie do grafiku tego lokalu.
          </span>
        </span>
        <Button
          variant="secondary"
          size="normal"
          disabled={readOnly || add.isPending}
          onClick={() => add.mutate({ locationId }, { onSuccess: () => void queryClient.invalidateQueries() })}
        >
          <UserPlus aria-hidden="true" size={20} />
          Dodaj mnie jako pracownika
        </Button>
      </div>
      {add.isError && <InlineError>{errorMessage(add.error, NETWORK_PROBLEM)}</InlineError>}
    </div>
  )
}

function hoursWords(e: EmployeeOut): string {
  const parts = []
  if (e.target_hours_month) parts.push(`cel ${e.target_hours_month} godz.`)
  if (e.max_hours_month) parts.push(`najwyżej ${e.max_hours_month} godz.`)
  return parts.length ? `${parts.join(', ')} w miesiącu` : 'bez limitu godzin'
}

function EmployeeList({
  employees,
  names,
  onEdit,
}: {
  employees: EmployeeOut[]
  names: Map<string, string>
  onEdit: (e: EmployeeOut) => void
}) {
  const { readOnly } = useManager()
  return (
    <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
      {employees.map((e) => (
        <li
          key={e.id}
          className="grid items-center gap-x-4 gap-y-1 border-b border-line px-4 py-3 last:border-b-0 md:grid-cols-[minmax(180px,1.2fr)_minmax(160px,1.3fr)_minmax(120px,auto)_minmax(160px,1.2fr)_auto]"
        >
          <span className="grid">
            <b>{`${e.first_name} ${e.last_name}`.trim() || 'Bez imienia'}</b>
            <span className="text-sm text-ink-muted tabular-nums">{prettyPhone(e.phone)}</span>
          </span>
          <span className="flex flex-wrap gap-1">
            {e.position_ids.length ? (
              e.position_ids.map((id) => <Tag key={id}>{names.get(id) ?? 'Stanowisko'}</Tag>)
            ) : (
              <Tag tone="warn">Bez stanowiska</Tag>
            )}
            {e.is_manager && <Tag tone="accent">Kierownik</Tag>}
            {e.is_home === false && <Tag>{`Lokal główny: ${e.home_location_name}`}</Tag>}
          </span>
          <span className="flex flex-wrap gap-1">
            <Tag tone={EXPERIENCE[e.experience].tone}>{EXPERIENCE[e.experience].label}</Tag>
            {e.position_experience
              .filter((level) => level.experience !== e.experience)
              .map((level) => (
                <Tag key={level.position_id} tone={EXPERIENCE[level.experience].tone}>
                  {`${names.get(level.position_id) ?? 'Stanowisko'}: ${EXPERIENCE[level.experience].label.toLowerCase()}`}
                </Tag>
              ))}
          </span>
          <span className="text-sm text-ink-muted">{hoursWords(e)}</span>
          <Button variant="quiet" size="normal" onClick={() => onEdit(e)} disabled={readOnly} aria-label={`Zmień: ${e.first_name} ${e.last_name}`}>
            <Pencil aria-hidden="true" size={18} />
            Zmień
          </Button>
        </li>
      ))}
    </ul>
  )
}

type Level = 1 | 2 | 3

const toNumber = (value: string) => (value.trim() === '' ? null : Number(value))

function EmployeeForm({
  employee,
  positions,
  locationId,
  onDone,
}: {
  employee: EmployeeOut
  positions: PositionOut[]
  locationId: string
  onDone: () => void
}) {
  const update = useUpdateEmployee()
  const queryClient = useQueryClient()
  const [chosen, setChosen] = useState<string[]>(employee.position_ids)
  const [experience, setExperience] = useState(employee.experience)
  // Levels that differ from the default on single positions (position id -> level).
  const [levels, setLevels] = useState<Record<string, Level>>(() =>
    Object.fromEntries(
      employee.position_experience
        .filter((level) => level.experience !== employee.experience)
        .map((level) => [level.position_id, level.experience]),
    ),
  )
  const [max, setMax] = useState(employee.max_hours_month?.toString() ?? '')
  const [target, setTarget] = useState(employee.target_hours_month?.toString() ?? '')
  const [active, setActive] = useState(employee.is_active)
  const [first, setFirst] = useState(employee.first_name)
  const [last, setLast] = useState(employee.last_name)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    // Positions and their levels change only in this location (a person can work in several).
    const data: EmployeeIn = { revision: employee.revision, location_id: locationId }
    if (first !== employee.first_name) data.first_name = first
    if (last !== employee.last_name) data.last_name = last
    if (experience !== employee.experience) data.experience = experience
    if (toNumber(max) !== employee.max_hours_month) data.max_hours_month = toNumber(max)
    if (toNumber(target) !== employee.target_hours_month) data.target_hours_month = toNumber(target)
    if (active !== employee.is_active) data.is_active = active
    if (chosen.length !== employee.position_ids.length || chosen.some((id) => !employee.position_ids.includes(id))) {
      data.position_ids = chosen
    }
    const originalLevels = employee.position_experience.filter((p) => p.experience !== employee.experience)
    if (chosen.some((id) => levels[id] !== originalLevels.find((p) => p.position_id === id)?.experience)) {
      data.position_experience = chosen.map((id) => ({ position_id: id, experience: levels[id] ?? experience }))
    }
    update.mutate(
      { employeeId: employee.id, data },
      {
        onError: (error) => {
          if (errorStatus(error) === 409) void queryClient.invalidateQueries()
        },
        onSuccess: () => {
          void queryClient.invalidateQueries()
          onDone()
        },
      },
    )
  }
  const toggle = (id: string) => setChosen((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]))
  // Experience, hours and switching off are shared by all the person's locations: the main location sets them.
  const shared = employee.is_home !== false

  return (
    <div className="grid gap-5">
      <form onSubmit={submit} className="grid gap-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Imię" value={first} onChange={(e) => setFirst(e.target.value)} maxLength={80} required />
          <TextField label="Nazwisko" value={last} onChange={(e) => setLast(e.target.value)} maxLength={80} />
          <p className="m-0 text-sm text-ink-muted sm:col-span-2">
            Numer {prettyPhone(employee.phone)} służy do logowania, więc zmienia go tylko administrator Grafikomatu.
          </p>
        </div>
        <fieldset className="m-0 grid gap-1 border-0 p-0">
          <legend className="mb-1 font-semibold">Stanowiska</legend>
          {positions.length === 0 && (
            <p className="m-0 text-sm text-ink-muted">Najpierw dodaj stanowiska w „Ustawieniach lokalu”.</p>
          )}
          {positions.map((p) => (
            <CheckField key={p.id} label={p.name} checked={chosen.includes(p.id)} onChange={() => toggle(p.id)} />
          ))}
        </fieldset>
        {shared && (
          <fieldset className="m-0 grid gap-1 border-0 p-0">
            <legend className="mb-1 font-semibold">Doświadczenie</legend>
            <p className="m-0 text-sm text-ink-muted">
              Widzisz to tylko Ty. Liczy się w zasadzie „Początkujący z doświadczonymi”.
            </p>
            {([1, 2, 3] as const).map((value) => (
              <label key={value} className="flex min-h-(--touch) cursor-pointer items-center gap-3">
                <input
                  type="radio"
                  name="experience"
                  className="size-6 accent-accent"
                  checked={experience === value}
                  onChange={() => setExperience(value)}
                />
                <span className="grid">
                  <span>{EXPERIENCE[value].label}</span>
                  <span className="text-sm text-ink-muted">{EXPERIENCE[value].hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}
        {chosen.length >= 2 && (
          <fieldset className="m-0 grid gap-2 border-0 p-0">
            <legend className="mb-1 font-semibold">Inny stopień na którymś stanowisku</legend>
            <p className="m-0 text-sm text-ink-muted">
              Np. ktoś doświadczony przy piecu dopiero uczy się kasy.
            </p>
            {positions
              .filter((p) => chosen.includes(p.id))
              .map((p) => (
                <label key={p.id} className="grid gap-1 sm:grid-cols-[1fr_minmax(200px,auto)] sm:items-center">
                  <span>{p.name}</span>
                  <select
                    className="min-h-(--touch) rounded-md border border-line bg-surface px-3 text-base text-ink"
                    aria-label={`Stopień na stanowisku ${p.name}`}
                    value={levels[p.id] ?? ''}
                    onChange={(event) => {
                      const value = event.target.value
                      setLevels((now) => {
                        const next = { ...now }
                        if (value === '') delete next[p.id]
                        else next[p.id] = Number(value) as Level
                        return next
                      })
                    }}
                  >
                    <option value="">{`Tak jak wyżej (${EXPERIENCE[experience].label.toLowerCase()})`}</option>
                    {([1, 2, 3] as const)
                      .filter((value) => value !== experience)
                      .map((value) => (
                        <option key={value} value={value}>
                          {EXPERIENCE[value].label}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
          </fieldset>
        )}
        {shared && (
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Cel godzin w miesiącu"
              type="number"
              inputMode="numeric"
              min={1}
              max={400}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              hint="Puste = bez celu."
            />
            <TextField
              label="Najwyżej godzin w miesiącu"
              type="number"
              inputMode="numeric"
              min={1}
              max={400}
              value={max}
              onChange={(e) => setMax(e.target.value)}
              hint="Puste = bez limitu."
            />
          </div>
        )}
        {!shared ? (
          <p className="m-0 text-sm text-ink-muted">
            {`Lokal główny tej osoby to ${employee.home_location_name}. Tu ustawiasz jej stanowiska w swoim lokalu. Doświadczenie, godziny i wyłączenie z grafiku ustawia kierownik lokalu głównego.`}
          </p>
        ) : (
          <CheckField
            label="W grafiku"
            hint="Dawne zmiany tej osoby zostaną."
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
          />
        )}
        {!active && employee.is_active && (employee.draft_shifts ?? 0) > 0 && (
          <p role="alert" className="m-0 rounded-sm bg-prefer-not-soft px-3 py-2 text-ink">
            {`Ta osoba ma ${shifts(employee.draft_shifts ?? 0)} w szkicu grafiku. Po zapisaniu ułóż grafik od nowa albo przenieś je ręcznie.`}
          </p>
        )}
        {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
        <Button type="submit" wide disabled={update.isPending}>
          Zapisz
        </Button>
      </form>
      <OwnRates employeeId={employee.id} positionIds={employee.position_ids} locationId={locationId} />
      <RemoveEmployee employee={employee} locationId={locationId} onDone={onDone} />
    </div>
  )
}

/** "Usuń z lokalu": for good, unlike switching off. Asks once more, because it cannot be undone from here.
 * A person who also works in other locations leaves only this one. */
function RemoveEmployee({
  employee,
  locationId,
  onDone,
}: {
  employee: EmployeeOut
  locationId: string
  onDone: () => void
}) {
  const remove = useRemoveEmployee()
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const name = `${employee.first_name} ${employee.last_name}`.trim() || 'Ta osoba'
  const others = employee.other_location_names ?? []
  if (!asking) {
    return (
      <Button variant="danger" size="normal" wide onClick={() => setAsking(true)}>
        <Trash2 aria-hidden="true" size={18} />
        Usuń z lokalu
      </Button>
    )
  }
  return (
    <div role="alert" className="grid gap-3 rounded-md border border-cannot bg-surface p-4">
      {others.length > 0 ? (
        <p className="m-0">
          <b>{`Usunąć z lokalu: ${name}?`}</b>{' '}
          {`Przestanie pracować w tym lokalu i zostanie w: ${others.join(', ')}. Zmiany, na które jest już wpisana, zostaną w grafikach.`}
        </p>
      ) : (
        <p className="m-0">
          <b>{`Usunąć z lokalu: ${name}?`}</b>{' '}
          {employee.is_manager
            ? 'Zniknie z listy pracowników i nie dostanie nowych zmian. Dalej będzie kierownikiem.'
            : 'Zniknie z listy i straci dostęp do firmy w Grafikomacie. Wróci tylko przez nowe zaproszenie.'}{' '}
          Zmiany w dawnych grafikach i godziny zostają.
        </p>
      )}
      {others.length === 0 && (employee.published_shifts ?? 0) > 0 && (
        <p className="m-0 rounded-sm bg-prefer-not-soft px-3 py-2 text-ink">
          {`Ta osoba ma jeszcze ${shifts(employee.published_shifts ?? 0)} w opublikowanym grafiku. Zostanie na nich wpisana, ale nie zobaczy już grafiku. Najpierw przenieś te zmiany na kogoś innego.`}
        </p>
      )}
      {others.length === 0 && (employee.draft_shifts ?? 0) > 0 && (
        <p className="m-0 rounded-sm bg-prefer-not-soft px-3 py-2 text-ink">
          {`Ta osoba ma ${shifts(employee.draft_shifts ?? 0)} w szkicu grafiku. Potem ułóż grafik od nowa albo przenieś je ręcznie.`}
        </p>
      )}
      {remove.isError && <InlineError>{errorMessage(remove.error, NETWORK_PROBLEM)}</InlineError>}
      <Button
        variant="danger"
        wide
        disabled={remove.isPending}
        onClick={() =>
          remove.mutate(
            { employeeId: employee.id, params: { location_id: locationId } },
            {
              onSuccess: () => {
                void queryClient.invalidateQueries()
                onDone()
              },
            },
          )
        }
      >
        Tak, usuń z lokalu
      </Button>
      <Button variant="secondary" wide onClick={() => setAsking(false)}>
        Zostaw
      </Button>
    </div>
  )
}

function InvitationsSection({ locationId, positions }: { locationId: string; positions: PositionOut[] }) {
  const { role, readOnly } = useManager()
  const invitations = useLocationInvitations(locationId)
  const invite = useInviteToLocation()
  const cancel = useCancelInvitation()
  const queryClient = useQueryClient()
  const [phone, setPhone] = useState('')
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [asManager, setAsManager] = useState(false)
  const [sent, setSent] = useState<string | null>(null)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    invite.mutate(
      {
        locationId,
        data: { phone, first_name: first, last_name: last, role: asManager ? 'manager' : 'employee' },
      },
      {
        onSuccess: (response) => {
          const out = response.data as InvitationOut
          setSent(
            `Zaproszenie czeka na numer ${prettyPhone(out.phone)}. Nie wysyłamy SMS-a, więc powiedz tej osobie, żeby zalogowała się w Grafikomacie tym numerem. Zaproszenie zobaczy od razu.`,
          )
          setPhone('')
          setFirst('')
          setLast('')
          void queryClient.invalidateQueries()
        },
      },
    )
  }
  const pending = ((invitations.data?.data as InvitationOut[] | undefined) ?? []).filter((i) => i.status === 'pending')
  const names = new Map(positions.map((p) => [p.id, p.name]))

  return (
    <Section
      title="Zaproś do lokalu"
      description="Ta osoba zaloguje się kodem z SMS-a i przyjmie zaproszenie. Listę osób wkleisz albo wgrasz w „Zaproś kilka osób”."
      action={<InviteManyButton locationId={locationId} positions={positions} />}
    >
      <form onSubmit={submit} className="grid gap-4 rounded-md border border-line bg-surface p-4 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end">
        <TextField label="Numer telefonu" type="tel" inputMode="tel" autoComplete="off" value={phone} onChange={(e) => setPhone(e.target.value)} required placeholder="512 345 678" />
        <TextField label="Imię (nieobowiązkowo)" value={first} onChange={(e) => setFirst(e.target.value)} maxLength={80} />
        <TextField label="Nazwisko (nieobowiązkowo)" value={last} onChange={(e) => setLast(e.target.value)} maxLength={120} />
        <Button type="submit" size="normal" disabled={invite.isPending || readOnly}>
          <UserPlus aria-hidden="true" size={20} />
          Zaproś
        </Button>
        {role === 'owner' && (
          <CheckField
            className="md:col-span-4"
            label="Jako kierownika tego lokalu"
            hint="Kierownik widzi ten panel i układa grafik."
            checked={asManager}
            onChange={(e) => setAsManager(e.target.checked)}
          />
        )}
        {sent && (
          <p role="status" className="m-0 rounded-sm bg-accent-soft px-3 py-2 text-accent md:col-span-4">
            {sent}
          </p>
        )}
        {invite.isError && (
          <div className="md:col-span-4">
            <InlineError>{errorMessage(invite.error, NETWORK_PROBLEM)}</InlineError>
          </div>
        )}
      </form>
      {invitations.isError && <InlineError>Nie udało się wczytać zaproszeń.</InlineError>}
      {pending.length > 0 && (
        <div className="grid gap-2">
          <h3 className="m-0 text-base font-extrabold">Czekają na odpowiedź ({pending.length})</h3>
          <ul className="m-0 grid list-none gap-2 p-0">
            {pending.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-line bg-surface px-4 py-2">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>
                    <b className="tabular-nums">{prettyPhone(i.phone)}</b>
                    {(i.first_name || i.last_name) && ` ${i.first_name} ${i.last_name}`}
                    {i.role === 'manager' && ' (kierownik)'}
                  </span>
                  {(i.position_ids ?? []).map((id) => (
                    <Tag key={id}>{names.get(id) ?? 'Stanowisko'}</Tag>
                  ))}
                </span>
                <Button
                  variant="quiet"
                  size="normal"
                  disabled={cancel.isPending || readOnly}
                  onClick={() => cancel.mutate({ invitationId: i.id }, { onSuccess: () => void queryClient.invalidateQueries() })}
                >
                  Anuluj zaproszenie
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  )
}
