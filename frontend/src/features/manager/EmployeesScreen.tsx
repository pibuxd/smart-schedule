import { useQueryClient } from '@tanstack/react-query'
import { Pencil, UserPlus } from 'lucide-react'
import { useState } from 'react'

import type { EmployeeOut, InvitationOut, LocationSetupOut, PositionOut } from '../../api/generated/model'
import { useLocationEmployees, useLocationSetup, useUpdateEmployee } from '../../api/generated/staffing/staffing'
import { useCancelInvitation, useInviteToLocation, useLocationInvitations } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { CheckField, Section, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { prettyPhone } from '../auth/phone'
import { useManager } from './ManagerContext'
import { CONTRACT, EXPERIENCE } from './words'

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
        description="Stanowiska mówią, na jakie zmiany można kogoś wpisać. Stopień doświadczenia widzisz tylko Ty: dzięki niemu na zmianie nie zostaną sami początkujący. Maksimum i cel godzin są wskazówką dla układania grafiku."
      >
        {active.length === 0 ? (
          <EmptyState title="Nikt jeszcze nie pracuje w tym lokalu">
            <p className="m-0">Zaproś pierwszą osobę po numerze telefonu w sekcji poniżej.</p>
          </EmptyState>
        ) : (
          <EmployeeList employees={active} names={names} onEdit={setEditing} />
        )}
      </Section>

      <InvitationsSection locationId={locationId} />

      {off.length > 0 && (
        <Section
          title={`Wyłączeni z grafiku (${off.length})`}
          description="Nie dostają nowych zmian, ale ich dawne grafiki zostają. Możesz ich włączyć z powrotem."
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
          <EmployeeForm key={editing.id} employee={editing} positions={positions} onDone={() => setEditing(null)} />
        )}
      </Sheet>
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
          className="grid items-center gap-x-4 gap-y-1 border-b border-line px-4 py-3 last:border-b-0 md:grid-cols-[minmax(180px,1.2fr)_minmax(160px,1.3fr)_minmax(120px,auto)_minmax(140px,1fr)_minmax(160px,1.2fr)_auto]"
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
          </span>
          <span>
            <Tag tone={EXPERIENCE[e.experience].tone}>{EXPERIENCE[e.experience].label}</Tag>
          </span>
          <span className="text-sm">{CONTRACT[e.contract]}</span>
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

const toNumber = (value: string) => (value.trim() === '' ? null : Number(value))

function EmployeeForm({ employee, positions, onDone }: { employee: EmployeeOut; positions: PositionOut[]; onDone: () => void }) {
  const update = useUpdateEmployee()
  const queryClient = useQueryClient()
  const [chosen, setChosen] = useState<string[]>(employee.position_ids)
  const [contract, setContract] = useState(employee.contract)
  const [experience, setExperience] = useState(employee.experience)
  const [max, setMax] = useState(employee.max_hours_month?.toString() ?? '')
  const [target, setTarget] = useState(employee.target_hours_month?.toString() ?? '')
  const [active, setActive] = useState(employee.is_active)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    update.mutate(
      {
        employeeId: employee.id,
        data: {
          position_ids: chosen,
          contract,
          experience,
          max_hours_month: toNumber(max),
          target_hours_month: toNumber(target),
          is_active: active,
        },
      },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries()
          onDone()
        },
      },
    )
  }
  const toggle = (id: string) => setChosen((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]))

  return (
    <form onSubmit={submit} className="grid gap-5">
      <fieldset className="m-0 grid gap-1 border-0 p-0">
        <legend className="mb-1 font-semibold">Stanowiska</legend>
        {positions.length === 0 && (
          <p className="m-0 text-sm text-ink-muted">Najpierw dodaj stanowiska w „Ustawieniach lokalu”.</p>
        )}
        {positions.map((p) => (
          <CheckField key={p.id} label={p.name} checked={chosen.includes(p.id)} onChange={() => toggle(p.id)} />
        ))}
      </fieldset>
      <fieldset className="m-0 grid gap-1 border-0 p-0">
        <legend className="mb-1 font-semibold">Doświadczenie</legend>
        <p className="m-0 text-sm text-ink-muted">
          Widzisz to tylko Ty, pracownik nie zobaczy swojego stopnia. Przy układaniu grafiku na zmianie ma być co
          najmniej tylu doświadczonych, ilu początkujących (zasada „Początkujący z doświadczonymi”).
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
      <fieldset className="m-0 grid gap-1 border-0 p-0">
        <legend className="mb-1 font-semibold">Umowa</legend>
        {(['civil', 'employment'] as const).map((value) => (
          <label key={value} className="flex min-h-(--touch) cursor-pointer items-center gap-3">
            <input
              type="radio"
              name="contract"
              className="size-6 accent-accent"
              checked={contract === value}
              onChange={() => setContract(value)}
            />
            {CONTRACT[value]}
          </label>
        ))}
        {contract === 'employment' && (
          <p className="m-0 text-sm text-ink-muted">
            Przy umowie o pracę Grafikomat zawsze pilnuje 11 godzin odpoczynku między zmianami, najwyżej 8 godzin
            pracy na dobę i 35 godzin wolnego w tygodniu. Sprawdzanie jest uproszczone (doba to dzień kalendarzowy,
            tydzień od poniedziałku) i nie zastępuje oceny kadrowej.
          </p>
        )}
      </fieldset>
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
      <CheckField
        label="W grafiku"
        hint="Odznacz, gdy ktoś odchodzi albo długo nie pracuje. Jego dawne zmiany zostaną w historii."
        checked={active}
        onChange={(e) => setActive(e.target.checked)}
      />
      {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={update.isPending}>
        Zapisz
      </Button>
    </form>
  )
}

function InvitationsSection({ locationId }: { locationId: string }) {
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
            `Zaproszenie zapisane dla ${prettyPhone(out.phone)}. Powiedz tej osobie, żeby zalogowała się w Grafikomacie tym numerem: zaproszenie zobaczy od razu. Nie wysyłamy SMS-a z zaproszeniem.`,
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

  return (
    <Section
      title="Zaproś do lokalu"
      description="Wpisz numer telefonu. Osoba zaloguje się kodem SMS i przyjmie zaproszenie w aplikacji."
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
                <span>
                  <b className="tabular-nums">{prettyPhone(i.phone)}</b>
                  {(i.first_name || i.last_name) && ` ${i.first_name} ${i.last_name}`}
                  {i.role === 'manager' && ' (kierownik)'}
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
