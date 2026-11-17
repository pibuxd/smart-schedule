import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, Navigate, Outlet, useNavigate } from '@tanstack/react-router'

import { useLogout } from '../api/generated/auth/auth'
import { ErrorState, Loading } from '../components/ui/status'
import { Wordmark } from '../components/Wordmark'
import { cn } from '../lib/cn'
import { ProfileNameForm } from '../features/auth/ProfileNameForm'
import { useSession } from '../features/auth/session'
import { AccessBanner } from '../features/manager/AccessBanner'
import { isManagerRole, ManagerContext } from '../features/manager/ManagerContext'
import { useWaitingClaims } from '../features/manager/waiting-claims'
import { useUnreadNotifications } from '../features/notifications/unread'

const MENU_LINK =
  'inline-flex min-h-(--touch) shrink-0 items-center gap-1.5 rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft'

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
        <ErrorState onRetry={session.retry}>{session.message}</ErrorState>
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
        <div className="mx-auto flex max-w-(--wide) flex-wrap items-center justify-between gap-x-4 px-4 pt-2 sm:py-2">
          <Link to="/kierownik" className="text-ink no-underline">
            <Wordmark />
          </Link>
          <div className="flex min-w-0 items-center gap-x-3 text-base text-ink-muted">
            <span className="hidden min-w-0 truncate sm:inline">{`${me.first_name} ${me.last_name}`.trim() || 'Twoje konto'}</span>
            {managed.length > 1 ? (
              <select
                aria-label="Firma"
                className="min-h-(--touch) max-w-48 rounded-sm border border-line bg-surface px-2 text-base"
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
              <span className="truncate font-semibold text-ink">{company.name}</span>
            )}
          </div>
          {/* On a phone the menu is one row that scrolls sideways, so it does not push the screen down. */}
          <nav
            aria-label="Menu kierownika"
            className="-mx-4 flex w-[calc(100%+2rem)] gap-x-1 overflow-x-auto px-2 text-base whitespace-nowrap sm:mx-0 sm:w-auto sm:flex-wrap sm:overflow-visible sm:px-0"
          >
            <Link to="/kierownik" activeOptions={{ exact: true }} className={MENU_LINK}>
              Lokale
            </Link>
            <Link to="/kierownik/pracownicy" className={MENU_LINK}>
              Pracownicy
            </Link>
            <OffersLink companyId={company.id} />
            <NotificationsLink companyId={company.id} />
            <Link to="/kierownik/godziny" className={MENU_LINK}>
              Godziny
            </Link>
            <Link to="/kierownik/dostep" className={MENU_LINK}>
              Dostęp
            </Link>
            {company.works_shifts && (
              <Link to="/grafik" className={MENU_LINK}>
                Mój grafik
              </Link>
            )}
            <button type="button" onClick={signOut} className={cn(MENU_LINK, 'cursor-pointer')}>
              Wyloguj
            </button>
          </nav>
        </div>
      </header>
      <AccessBanner companyId={company.id} />
      <main key={company.id} className="mx-auto grid max-w-(--wide) grid-cols-1 gap-6 px-4 pt-5 pb-16">
        {!me.first_name && <ProfileNameForm me={me} />}
        <Outlet />
      </main>
    </ManagerContext.Provider>
  )
}

/** "Oddane zmiany", with the number of volunteers waiting for a decision. */
function OffersLink({ companyId }: { companyId: string }) {
  const waiting = useWaitingClaims(companyId)
  return (
    <Link to="/kierownik/oddane-zmiany" className={MENU_LINK}>
      Oddane zmiany
      {waiting > 0 && (
        <span className="rounded-full bg-accent px-2 text-sm text-accent-ink no-underline" aria-label={`czeka: ${waiting}`}>
          {waiting}
        </span>
      )}
    </Link>
  )
}

/** My notifications (also "someone gives a shift away" for the manager), with the number of new ones. */
function NotificationsLink({ companyId }: { companyId: string }) {
  const unread = useUnreadNotifications(companyId)
  return (
    <Link to="/kierownik/powiadomienia" className={MENU_LINK}>
      Powiadomienia
      {unread > 0 && (
        <span className="rounded-full bg-accent px-2 text-sm text-accent-ink no-underline" aria-label={`nowe: ${unread}`}>
          {unread}
        </span>
      )}
    </Link>
  )
}
