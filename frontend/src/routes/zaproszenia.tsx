import { createFileRoute, Navigate } from '@tanstack/react-router'

import { Loading } from '../components/ui/status'
import { InvitationsScreen } from '../features/auth/InvitationsScreen'
import { useSession } from '../features/auth/session'

export const Route = createFileRoute('/zaproszenia')({
  component: InvitationsPage,
})

function InvitationsPage() {
  const session = useSession()
  if (session.state === 'loading') return <Loading>Otwieram Grafikomat…</Loading>
  if (session.state !== 'ready') return <Navigate to="/logowanie" replace />
  const name = `${session.me.first_name} ${session.me.last_name}`.trim()
  return <InvitationsScreen name={name} />
}
