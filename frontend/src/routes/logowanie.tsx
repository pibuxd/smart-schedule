import { createFileRoute, Navigate } from '@tanstack/react-router'

import { Loading } from '../components/ui/status'
import { LoginScreen } from '../features/auth/LoginScreen'
import { useSession } from '../features/auth/session'

export const Route = createFileRoute('/logowanie')({
  component: LoginPage,
})

function LoginPage() {
  // Asking who is logged in also sets the CSRF cookie the login form needs.
  const session = useSession()
  if (session.state === 'loading') return <Loading>Otwieram Grafikomat…</Loading>
  if (session.state === 'ready') return <Navigate to="/" replace />
  return <LoginScreen />
}
