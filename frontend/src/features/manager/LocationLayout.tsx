import { Link, Outlet } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'

import type { LocationOut } from '../../api/generated/model'
import { useLocationDetail } from '../../api/generated/tenancy/tenancy'
import { ErrorState, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import { AssistantDrawerProvider, OpenAssistantButton } from './AssistantDrawer'
import { useManager } from './ManagerContext'

const TABS = [
  { to: '/kierownik/lokal/$locationId/dyspozycje', label: 'Dyspozycje' },
  { to: '/kierownik/lokal/$locationId/grafik', label: 'Grafik' },
  { to: '/kierownik/lokal/$locationId/asystent', label: 'Ustalenia' },
  { to: '/kierownik/lokal/$locationId/pracownicy', label: 'Pracownicy' },
  { to: '/kierownik/lokal/$locationId/ustawienia', label: 'Ustawienia lokalu' },
  { to: '/kierownik/lokal/$locationId/zasady', label: 'Zasady' },
] as const

/** One location: its tabs, and the assistant chat that slides in from the right over any of them. */
export function LocationLayout({ locationId }: { locationId: string }) {
  const { readOnly } = useManager()
  const location = useLocationDetail(locationId)
  if (location.isPending) return <Loading>Wczytuję lokal…</Loading>
  if (location.isError) {
    return (
      <ErrorState onRetry={() => void location.refetch()}>
        {errorMessage(location.error, 'Nie udało się wczytać lokalu. Sprawdź internet i spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = location.data.data as LocationOut
  return (
    <AssistantDrawerProvider key={locationId} locationId={locationId}>
      <div className="grid min-w-0 grid-cols-1 gap-5">
        <div className="grid gap-2">
          <Link
            to="/kierownik"
            className="inline-flex min-h-(--touch) w-fit items-center gap-1.5 font-semibold text-accent underline underline-offset-4"
          >
            <ArrowLeft aria-hidden="true" size={20} />
            Wszystkie lokale
          </Link>
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <h1 className="m-0 text-2xl font-extrabold">{data.name}</h1>
              {data.group_name && <span className="text-ink-muted">{data.group_name}</span>}
              {data.archived && <span className="font-semibold text-cannot">W archiwum</span>}
            </div>
            {!readOnly && !data.archived && <OpenAssistantButton />}
          </div>
        </div>
        <nav aria-label="Ekrany lokalu" className="flex min-w-0 flex-wrap gap-1 border-b border-line">
          {TABS.map((tab) => (
            <Link
              key={tab.to}
              to={tab.to}
              params={{ locationId }}
              className="inline-flex min-h-(--touch) shrink-0 items-center border-b-2 px-3 text-sm font-semibold no-underline transition-colors"
              inactiveProps={{
                className: 'border-transparent text-ink-muted hover:text-accent',
              }}
              activeProps={{
                className: 'border-accent text-accent',
                'aria-current': 'page',
              }}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
        <Outlet />
      </div>
    </AssistantDrawerProvider>
  )
}
