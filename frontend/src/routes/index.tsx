import { createFileRoute, Navigate } from '@tanstack/react-router'

import { ErrorState, Loading } from '../components/ui/status'
import { useSession } from '../features/auth/session'
import { isManagerRole } from '../features/manager/ManagerContext'

export const Route = createFileRoute('/')({
  component: StartPage,
})

/** Sends the person where they need to be: login, invitations, or their schedule. */
function StartPage() {
  const session = useSession()
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
  if (session.me.pending_invitations > 0 || !session.company) return <Navigate to="/zaproszenia" replace />
  if (session.me.companies.some((c) => isManagerRole(c.role))) return <Navigate to="/kierownik" replace />
  return <Navigate to="/grafik" replace />
}
