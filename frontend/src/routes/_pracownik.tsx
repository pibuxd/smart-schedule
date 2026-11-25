import { createFileRoute, Link, Navigate, Outlet } from '@tanstack/react-router'
import { Bell, CalendarCheck, CalendarDays } from 'lucide-react'

import { ErrorState, Loading } from '../components/ui/status'
import { EmployeeContext } from '../features/auth/EmployeeContext'
import { EmployeeChatProvider, EmployeeChatTab } from '../features/availability/EmployeeChat'
import { MyDataButton } from '../features/auth/MyData'
import { ProfileNameForm } from '../features/auth/ProfileNameForm'
import { useSession } from '../features/auth/session'
import { useSignOut } from '../features/auth/sign-out'
import { isManagerRole } from '../features/manager/ManagerContext'
import { useUnreadNotifications } from '../features/notifications/unread'

export const Route = createFileRoute('/_pracownik')({
  component: EmployeeLayout,
})

const HEADER_LINK =
  'min-h-(--touch) shrink-0 cursor-pointer rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft'

const TABS = [
  { to: '/grafik', label: 'Mój grafik', Icon: CalendarDays },
  { to: '/kiedy-moge', label: 'Kiedy mogę', Icon: CalendarCheck },
  { to: '/powiadomienia', label: 'Powiadomienia', Icon: Bell },
] as const

/**
 * The employee's screens with tabs: at the bottom on a phone (thumb reach), at the top on a computer. The assistant
 * is always one tap away: the last tab on a phone, the corner button on a computer (`EmployeeChatProvider`).
 */
function EmployeeLayout() {
  const session = useSession()
  const signOut = useSignOut()

  if (session.state === 'loading') return <Loading>Otwieram Grafikomat…</Loading>
  if (session.state === 'logged-out') return <Navigate to="/logowanie" replace />
  if (session.state === 'error') {
    return (
      <main className="mx-auto max-w-(--column) px-4 py-10">
        <ErrorState onRetry={session.retry}>{session.message}</ErrorState>
      </main>
    )
  }
  const { me, company } = session
  if (!company) return <Navigate to="/zaproszenia" replace />

  return (
    <EmployeeContext.Provider value={{ companyId: company.id, readOnly: company.read_only }}>
      <EmployeeChatProvider key={company.id} companyId={company.id} readOnly={company.read_only}>
        <div className="pb-[calc(76px+env(safe-area-inset-bottom))] md:pb-0 [@media(max-height:500px)]:pb-0">
          <header className="mx-auto grid max-w-(--column) gap-3 px-4 pt-4">
            <div className="flex min-w-0 items-center justify-between gap-3 text-base text-ink-muted">
              <span className="min-w-0 truncate">
                {`${me.first_name} ${me.last_name}`.trim() || 'Twoje konto'}
                {me.companies.length === 1 && <span>, {company.name}</span>}
              </span>
              <span className="flex shrink-0 items-center">
                <MyDataButton me={me} className={`${HEADER_LINK} inline-flex items-center gap-1.5`} />
                <button type="button" onClick={signOut} className={HEADER_LINK}>
                  Wyloguj
                </button>
              </span>
            </div>
            {me.companies.length > 1 && (
              <select
                aria-label="Firma"
                className="w-full min-w-0 min-h-(--touch) rounded-sm border border-line bg-surface px-2 text-base"
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
            {isManagerRole(company.role) && (
              <Link
                to="/kierownik"
                className="rounded-md border-2 border-accent bg-surface px-3.5 py-2.5 font-semibold text-accent"
              >
                Przejdź do panelu kierownika
              </Link>
            )}
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
              'fixed inset-x-0 bottom-0 z-30 grid border-t border-line bg-surface md:grid-cols-[repeat(3,minmax(max-content,1fr))] ' +
              (company.read_only
                ? 'grid-cols-[repeat(3,minmax(max-content,1fr))] '
                : 'grid-cols-[repeat(4,minmax(max-content,1fr))] ') +
              'pb-[env(safe-area-inset-bottom)] md:static md:mx-auto md:mt-4 md:max-w-(--column) md:rounded-md md:border ' +
              // A phone lying on its side has no room for a fixed bar: the tabs stay at the top of the page.
              '[@media(max-height:500px)]:static'
            }
          >
            {TABS.map(({ to, label, Icon }) => (
              <Link
                key={to}
                to={to}
                className="relative grid min-h-16 min-w-0 place-items-center gap-0.5 px-0.5 py-2 text-sm font-semibold whitespace-nowrap"
                inactiveProps={{ className: 'text-ink-muted' }}
                activeProps={{
                  className:
                    'text-accent before:absolute before:inset-x-[24%] before:top-0 before:h-1 before:rounded-b-sm before:bg-accent',
                  'aria-current': 'page',
                }}
              >
                <span className="relative">
                  <Icon aria-hidden="true" size={26} />
                  {to === '/powiadomienia' && <UnreadBadge companyId={company.id} />}
                </span>
                {label}
              </Link>
            ))}
            <EmployeeChatTab className="md:hidden" />
          </nav>
          <main key={company.id} className="mx-auto max-w-(--column) px-4 pt-4 pb-10">
            {!me.first_name && <ProfileNameForm me={me} />}
            <Outlet />
          </main>
        </div>
      </EmployeeChatProvider>
    </EmployeeContext.Provider>
  )
}

/** Number of new notifications on the bell (red-free: accent colour, plus the number itself). */
function UnreadBadge({ companyId }: { companyId: string }) {
  const unread = useUnreadNotifications(companyId)
  if (unread === 0) return null
  return (
    <span
      aria-label={`nowe: ${unread}`}
      className="absolute -top-1.5 -right-3 min-w-6 rounded-full bg-accent px-1.5 text-center text-sm leading-6 text-accent-ink"
    >
      {unread > 9 ? '9+' : unread}
    </span>
  )
}
