import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, Navigate, Outlet, useNavigate } from '@tanstack/react-router'
import { CalendarCheck, CalendarDays } from 'lucide-react'

import { useLogout } from '../api/generated/auth/auth'
import { ErrorState, Loading } from '../components/ui/status'
import { EmployeeContext } from '../features/auth/EmployeeContext'
import { useSession } from '../features/auth/session'

export const Route = createFileRoute('/_pracownik')({
  component: EmployeeLayout,
})

const TABS = [
  { to: '/grafik', label: 'Mój grafik', Icon: CalendarDays },
  { to: '/kiedy-moge', label: 'Kiedy mogę', Icon: CalendarCheck },
] as const

/** The employee's two screens with tabs: at the bottom on a phone (thumb reach), at the top on a computer. */
function EmployeeLayout() {
  const session = useSession()
  const logout = useLogout()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  if (session.state === 'loading') return <Loading>Otwieram Grafikomat…</Loading>
  if (session.state === 'logged-out') return <Navigate to="/logowanie" replace />
  if (session.state === 'error') {
    return (
      <main className="mx-auto max-w-(--column) px-4 py-10">
        <ErrorState onRetry={session.retry}>
          Nie udało się połączyć z serwerem. Sprawdź internet i spróbuj jeszcze raz.
        </ErrorState>
      </main>
    )
  }
  const { me, company } = session
  if (!company) return <Navigate to="/zaproszenia" replace />

  const signOut = () =>
    logout.mutate(undefined, {
      onSettled: async () => {
        queryClient.clear()
        await navigate({ to: '/logowanie' })
      },
    })

  return (
    <EmployeeContext.Provider value={{ companyId: company.id, readOnly: company.read_only }}>
      <div className="pb-[calc(76px+env(safe-area-inset-bottom))] md:pb-0">
        <header className="mx-auto grid max-w-(--column) gap-3 px-4 pt-4">
          <div className="flex min-w-0 items-center justify-between gap-3 text-base text-ink-muted">
            <span className="min-w-0 truncate">
              {`${me.first_name} ${me.last_name}`.trim() || 'Twoje konto'}
              {me.companies.length > 1 && (
                <select
                  aria-label="Firma"
                  className="ml-2 min-h-(--touch) rounded-sm border border-line bg-surface px-2 text-base"
                  value={company.id}
                  onChange={(event) => session.chooseCompany(event.target.value)}
                >
                  {me.companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
              {me.companies.length === 1 && <span>, {company.name}</span>}
            </span>
            <button
              type="button"
              onClick={signOut}
              className="min-h-(--touch) shrink-0 cursor-pointer rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft"
            >
              Wyloguj
            </button>
          </div>
          {me.pending_invitations > 0 && (
            <Link
              to="/zaproszenia"
              className="rounded-md border-2 border-accent bg-accent-soft px-3.5 py-2.5 font-semibold text-accent"
            >
              Masz nowe zaproszenie do pracy. Zobacz
            </Link>
          )}
        </header>
        <nav
          aria-label="Ekrany"
          className={
            'fixed inset-x-0 bottom-0 z-30 grid grid-cols-2 border-t border-line bg-surface ' +
            'pb-[env(safe-area-inset-bottom)] md:static md:mx-auto md:mt-4 md:max-w-(--column) md:rounded-md md:border'
          }
        >
          {TABS.map(({ to, label, Icon }) => (
            <Link
              key={to}
              to={to}
              className="relative grid min-h-16 place-items-center gap-0.5 py-2 text-base font-semibold"
              inactiveProps={{ className: 'text-ink-muted' }}
              activeProps={{
                className:
                  'text-accent before:absolute before:inset-x-[24%] before:top-0 before:h-1 before:rounded-b-sm before:bg-accent',
                'aria-current': 'page',
              }}
            >
              <Icon aria-hidden="true" size={26} />
              {label}
            </Link>
          ))}
        </nav>
        <main className="mx-auto max-w-(--column) px-4 pt-4 pb-10">
          <Outlet />
        </main>
      </div>
    </EmployeeContext.Provider>
  )
}
