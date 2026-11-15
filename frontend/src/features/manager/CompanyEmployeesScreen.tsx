import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import type { EmployeeOut, LocationSummaryOut, ManagerOverviewOut } from '../../api/generated/model'
import { useLocationEmployees } from '../../api/generated/staffing/staffing'
import { useManagerOverview } from '../../api/generated/tenancy/tenancy'
import { TextField } from '../../components/ui/field'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import { prettyPhone } from '../auth/phone'
import { useManager } from './ManagerContext'

const fullName = (e: EmployeeOut) => `${e.first_name} ${e.last_name}`.trim() || 'Bez imienia'

/** Everyone in the company's locations on one page, with a search; changes are made in the person's location. */
export function CompanyEmployeesScreen() {
  const { companyId } = useManager()
  const overview = useManagerOverview({ company_id: companyId })
  const [query, setQuery] = useState('')

  if (overview.isPending) return <Loading>Wczytuję lokale…</Loading>
  if (overview.isError) {
    return (
      <ErrorState onRetry={() => void overview.refetch()}>
        {errorMessage(overview.error, 'Nie udało się wczytać lokali. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = overview.data.data as ManagerOverviewOut
  return (
    <div className="grid gap-6">
      <div className="grid gap-1">
        <h1 className="m-0 text-2xl font-extrabold">Pracownicy</h1>
        <p className="m-0 max-w-[62ch] text-ink-muted">
          Wszyscy z Twoich lokali. Żeby coś zmienić u osoby, otwórz jej lokal.
        </p>
      </div>
      {data.locations.length === 0 ? (
        <EmptyState title="Nie masz jeszcze żadnego lokalu">
          <p className="m-0">Dodaj lokal na stronie „Lokale”, potem zaproś do niego pracowników.</p>
        </EmptyState>
      ) : (
        <>
          <TextField
            label="Szukaj po imieniu, nazwisku albo numerze"
            type="search"
            className="max-w-md"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {data.locations.map((location) => (
            <LocationPeople key={location.id} location={location} query={query} />
          ))}
        </>
      )}
    </div>
  )
}

function matches(e: EmployeeOut, query: string): boolean {
  const words = query.toLowerCase().trim()
  if (!words) return true
  const digits = words.replace(/\D/g, '')
  return fullName(e).toLowerCase().includes(words) || (digits.length >= 3 && e.phone.includes(digits))
}

function LocationPeople({ location, query }: { location: LocationSummaryOut; query: string }) {
  const employees = useLocationEmployees(location.id)
  const list = ((employees.data?.data as EmployeeOut[] | undefined) ?? []).filter((e) => e.is_active && matches(e, query))
  return (
    <section className="grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-ink pb-1.5">
        <h2 className="m-0 text-lg font-extrabold">{location.name}</h2>
        <Link
          to="/kierownik/lokal/$locationId/pracownicy"
          params={{ locationId: location.id }}
          className="inline-flex min-h-(--touch) items-center font-semibold text-accent underline underline-offset-4"
        >
          Zmień albo zaproś w tym lokalu
        </Link>
      </div>
      {employees.isPending && <Loading>Wczytuję pracowników…</Loading>}
      {employees.isError && <InlineError>{errorMessage(employees.error, 'Nie udało się wczytać pracowników tego lokalu.')}</InlineError>}
      {employees.isSuccess &&
        (list.length === 0 ? (
          <p className="m-0 text-ink-muted">{query ? 'Nikt tu nie pasuje do wyszukiwania.' : 'Nikogo jeszcze nie ma w grafiku.'}</p>
        ) : (
          <ul className="m-0 grid list-none overflow-hidden rounded-md border border-line bg-surface p-0">
            {list.map((e) => (
              <li key={e.id} className="flex flex-wrap justify-between gap-x-4 border-b border-line px-4 py-2 last:border-b-0">
                <b>{fullName(e)}</b>
                <span className="text-ink-muted tabular-nums">{prettyPhone(e.phone)}</span>
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}
