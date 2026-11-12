import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'

import type { LocationSummaryOut, ManagerOverviewOut } from '../../api/generated/model'
import { useCreateLocation, useManagerOverview, useUpdateLocation } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { SelectField, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { AskAvailabilityButton } from './AskAvailabilityButton'
import { useManager } from './ManagerContext'
import { daysUntil, deadlineWords, namesList, PERIOD_STATUS, people, periodTitle, shortDay } from './words'

/** The manager's start screen: every location in one list, where its availability collection stands. */
export function OverviewScreen({ today = new Date() }: { today?: Date }) {
  const { companyId, role } = useManager()
  const overview = useManagerOverview({ company_id: companyId })
  const [adding, setAdding] = useState(false)

  if (overview.isPending) return <Loading>Wczytuję lokale…</Loading>
  if (overview.isError) {
    return (
      <ErrorState onRetry={() => void overview.refetch()}>
        {errorMessage(overview.error, 'Nie udało się wczytać lokali. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = overview.data.data as ManagerOverviewOut
  const byGroup = new Map<string, { name: string; id: string | null; locations: LocationSummaryOut[] }>()
  for (const location of data.locations) {
    const key = location.group_id ?? ''
    if (!byGroup.has(key)) byGroup.set(key, { id: location.group_id, name: location.group_name ?? 'Bez grupy', locations: [] })
    byGroup.get(key)!.locations.push(location)
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="m-0 text-2xl font-extrabold">Lokale</h1>
          <p className="m-0 max-w-[62ch] text-ink-muted">
            Każdy lokal ma własny termin dyspozycji. Grafik układasz sam, gdy termin minie albo gdy wszyscy wpiszą
            dyspozycje.
          </p>
        </div>
        {role === 'owner' && (
          <Button variant="secondary" size="normal" onClick={() => setAdding(true)} disabled={data.subscription.read_only}>
            <Plus aria-hidden="true" size={20} />
            Nowy lokal
          </Button>
        )}
      </div>

      {data.locations.length === 0 && (
        <EmptyState title="Nie masz jeszcze żadnego lokalu">
          <p className="m-0">
            {role === 'owner'
              ? 'Dodaj pierwszy lokal przyciskiem „Nowy lokal”. Potem ustawisz w nim stanowiska, zmiany i obsadę.'
              : 'Właściciel firmy nie przypisał Ci jeszcze lokalu. Poproś go o to.'}
          </p>
        </EmptyState>
      )}

      {[...byGroup.values()].map((group) => (
        <section key={group.id ?? 'none'} className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-ink pb-1.5">
            <h2 className="m-0 text-lg font-extrabold">{group.name}</h2>
            {group.id && (
              <Link
                to="/kierownik/grupa/$groupId/zasady"
                params={{ groupId: group.id }}
                className="inline-flex min-h-(--touch) items-center font-semibold text-accent underline underline-offset-4"
              >
                Zasady wspólne dla grupy
              </Link>
            )}
          </div>
          <ul className="m-0 grid list-none gap-3 p-0">
            {group.locations.map((location) => (
              <LocationRow key={location.id} location={location} today={today} readOnly={data.subscription.read_only} />
            ))}
          </ul>
        </section>
      ))}

      {data.archived.length > 0 && <ArchivedList data={data} />}
      <NewLocationSheet open={adding} onOpenChange={setAdding} data={data} />
    </div>
  )
}

function readiness(location: LocationSummaryOut, today: Date): { text: string; tone: 'accent' | 'muted' } | null {
  const period = location.period
  if (!period || period.status !== 'collecting') return null
  if (location.employees > 0 && period.missing.length === 0) {
    return { text: 'Wszyscy wpisali dyspozycje. Można układać grafik.', tone: 'accent' }
  }
  if (daysUntil(period.deadline, today) < 0) {
    return {
      text: `Termin minął. Można układać grafik (bez dyspozycji: ${people(period.missing.length)}).`,
      tone: 'accent',
    }
  }
  return null
}

function LocationRow({ location, today, readOnly }: { location: LocationSummaryOut; today: Date; readOnly: boolean }) {
  const period = location.period
  const ready = readiness(location, today)
  const linkClass =
    'inline-flex min-h-(--touch) items-center rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft'
  return (
    <li className="grid gap-4 rounded-md border border-line bg-surface p-4 lg:grid-cols-[minmax(200px,1.1fr)_minmax(220px,1.2fr)_minmax(240px,1.5fr)_auto]">
      <div className="grid content-start gap-1">
        <Link
          to="/kierownik/lokal/$locationId/dyspozycje"
          params={{ locationId: location.id }}
          className="text-lg font-extrabold text-ink underline-offset-4 hover:underline"
        >
          {location.name}
        </Link>
        {location.address && <span className="text-sm text-ink-muted">{location.address}</span>}
        <span className="text-sm text-ink-muted">
          {people(location.employees)} w grafiku
          {location.pending_invitations > 0 && `, zaproszenia bez odpowiedzi: ${location.pending_invitations}`}
        </span>
      </div>

      <div className="grid content-start gap-1">
        {period ? (
          <>
            <span className="font-semibold">Grafik {periodTitle(period.start, period.end)}</span>
            <span>
              <Tag tone={period.status === 'collecting' ? 'accent' : 'muted'}>{PERIOD_STATUS[period.status]}</Tag>
            </span>
            {period.status === 'collecting' && (
              <span className="text-sm text-ink-muted">
                Termin: {shortDay(period.deadline)} ({deadlineWords(period.deadline, today)})
              </span>
            )}
          </>
        ) : (
          <>
            <span className="font-semibold">Brak okresu grafiku</span>
            <span className="text-sm text-ink-muted">Ustal daty okresu i termin dyspozycji.</span>
          </>
        )}
      </div>

      <div className="grid content-start gap-1.5">
        {period && period.status === 'collecting' && (
          <>
            <Progress done={period.submitted} total={location.employees} />
            {period.missing.length > 0 && (
              <span className="text-sm">
                <span className="text-ink-muted">Jeszcze nie: </span>
                {namesList(period.missing)}
              </span>
            )}
            {period.late_days > 0 && (
              <span>
                <Tag tone="warn">Zmiany po terminie: {period.late_days} dni</Tag>
              </span>
            )}
            {ready && <span className="font-semibold text-accent">{ready.text}</span>}
          </>
        )}
      </div>

      <div className="flex flex-wrap content-start items-start gap-2 lg:grid lg:justify-items-end">
        {period?.status === 'collecting' && (
          <AskAvailabilityButton
            periodId={period.id}
            missing={period.missing.length}
            asked={period.availability_requested_at !== null}
            disabled={readOnly}
          />
        )}
        <div className="flex flex-wrap gap-x-1 lg:justify-end">
          <Link to="/kierownik/lokal/$locationId/dyspozycje" params={{ locationId: location.id }} className={linkClass}>
            Dyspozycje
          </Link>
          <Link to="/kierownik/lokal/$locationId/pracownicy" params={{ locationId: location.id }} className={linkClass}>
            Pracownicy
          </Link>
          <Link to="/kierownik/lokal/$locationId/ustawienia" params={{ locationId: location.id }} className={linkClass}>
            Ustawienia
          </Link>
          <Link to="/kierownik/lokal/$locationId/zasady" params={{ locationId: location.id }} className={linkClass}>
            Zasady
          </Link>
        </div>
      </div>
    </li>
  )
}

/** "12 z 18 wpisało" with a bar made of squares, like boxes ticked on paper. */
export function Progress({ done, total }: { done: number; total: number }) {
  const share = total ? Math.round((done / total) * 100) : 0
  return (
    <div className="grid gap-1">
      <span className="font-semibold">
        Wpisali: {done} z {total}
      </span>
      <div
        role="progressbar"
        aria-label="Kto wpisał dyspozycje"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        className="h-3 overflow-hidden rounded-sm border border-ink bg-surface"
      >
        <div className="h-full bg-accent" style={{ width: `${share}%` }} />
      </div>
    </div>
  )
}

function ArchivedList({ data }: { data: ManagerOverviewOut }) {
  const { role } = useManager()
  const update = useUpdateLocation()
  const queryClient = useQueryClient()
  return (
    <section className="grid gap-2">
      <h2 className="m-0 text-lg font-extrabold">Archiwum</h2>
      <p className="m-0 text-sm text-ink-muted">
        Zarchiwizowane lokale zachowują historię grafików, ale nie pojawiają się na liście i nie da się dla nich
        układać grafiku.
      </p>
      <ul className="m-0 grid list-none gap-2 p-0">
        {data.archived.map((location) => (
          <li key={location.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-line bg-surface px-4 py-2">
            <span>{location.name}</span>
            {role === 'owner' && (
              <Button
                variant="quiet"
                size="normal"
                disabled={update.isPending || data.subscription.read_only}
                onClick={() =>
                  update.mutate(
                    { locationId: location.id, data: { archived: false } },
                    { onSuccess: () => void queryClient.invalidateQueries() },
                  )
                }
              >
                Przywróć
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function NewLocationSheet({
  open,
  onOpenChange,
  data,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  data: ManagerOverviewOut
}) {
  const create = useCreateLocation()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [groupId, setGroupId] = useState('')
  const [period, setPeriod] = useState<'month' | 'week'>('month')

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(
      {
        data: {
          company_id: data.company_id,
          name,
          address,
          group_id: groupId || null,
          schedule_period: period,
        },
      },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries()
          setName('')
          setAddress('')
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Nowy lokal">
      <form onSubmit={submit} className="grid gap-4">
        <TextField label="Nazwa" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        <TextField label="Adres (nieobowiązkowo)" value={address} onChange={(e) => setAddress(e.target.value)} maxLength={300} />
        {data.groups.length > 0 && (
          <SelectField label="Grupa lokali" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
            <option value="">Bez grupy (własne zasady)</option>
            {data.groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </SelectField>
        )}
        <SelectField label="Grafik układany na" value={period} onChange={(e) => setPeriod(e.target.value as 'month' | 'week')}>
          <option value="month">miesiąc</option>
          <option value="week">tydzień</option>
        </SelectField>
        {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
        <Button type="submit" wide disabled={create.isPending}>
          Dodaj lokal
        </Button>
      </form>
    </Sheet>
  )
}
