import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, Navigate, Outlet, useNavigate } from '@tanstack/react-router'

import { useLogout } from '../api/generated/auth/auth'
import { ErrorState, Loading } from '../components/ui/status'
import { Wordmark } from '../components/Wordmark'
import { useSession } from '../features/auth/session'
import { isManagerRole, ManagerContext } from '../features/manager/ManagerContext'

export const Route = createFileRoute('/kierownik')({
  component: ManagerLayout,
})

/** The manager's panel: made for a computer first (wide tables), still usable on a phone. */
function ManagerLayout() {
  const session = useSession()
  const logout = useLogout()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  if (session.state === 'loading') return <Loading>Otwieram panel kierownika…</Loading>
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
  const { me } = session
  const managed = me.companies.filter((c) => isManagerRole(c.role))
  const company = managed.find((c) => c.id === session.company?.id) ?? managed[0]
  if (!company || !isManagerRole(company.role)) return <Navigate to="/grafik" replace />

  const signOut = () =>
    logout.mutate(undefined, {
      onSettled: async () => {
        queryClient.clear()
        await navigate({ to: '/logowanie' })
      },
    })

  return (
    <ManagerContext.Provider value={{ companyId: company.id, role: company.role, readOnly: company.read_only }}>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-(--wide) flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2">
          <Link to="/kierownik" className="text-ink no-underline">
            <Wordmark />
          </Link>
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 text-base text-ink-muted">
            <span className="min-w-0 truncate">{`${me.first_name} ${me.last_name}`.trim() || 'Twoje konto'}</span>
            {managed.length > 1 ? (
              <select
                aria-label="Firma"
                className="min-h-(--touch) rounded-sm border border-line bg-surface px-2 text-base"
                value={company.id}
                onChange={(event) => session.chooseCompany(event.target.value)}
              >
                {managed.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-semibold text-ink">{company.name}</span>
            )}
            <Link
              to="/grafik"
              className="inline-flex min-h-(--touch) items-center rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft"
            >
              Mój grafik
            </Link>
            <button
              type="button"
              onClick={signOut}
              className="min-h-(--touch) cursor-pointer rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft"
            >
              Wyloguj
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto grid max-w-(--wide) gap-6 px-4 pt-5 pb-16">
        <Outlet />
      </main>
    </ManagerContext.Provider>
  )
}
