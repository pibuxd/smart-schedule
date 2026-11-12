import { createFileRoute } from '@tanstack/react-router'

import { ErrorState, Loading } from '../components/ui/status'
import { LoginScreen } from '../features/auth/LoginScreen'
import { useSession } from '../features/auth/session'
import { RegisterCompanyScreen } from '../features/company/RegisterCompanyScreen'

export const Route = createFileRoute('/rejestracja')({
  component: RegisterPage,
})

/** A new manager: confirm the phone number with a code, then name the company. */
function RegisterPage() {
  const session = useSession()
  if (session.state === 'loading') return <Loading>Otwieram Grafikomat…</Loading>
  if (session.state === 'logged-out') return <LoginScreen purpose="register" />
  if (session.state === 'error') {
    return (
      <main className="mx-auto max-w-(--column) px-4 py-10">
        <ErrorState onRetry={session.retry}>
          Nie udało się połączyć z serwerem. Sprawdź internet i spróbuj jeszcze raz.
        </ErrorState>
      </main>
    )
  }
  return <RegisterCompanyScreen me={session.me} onCreated={session.chooseCompany} />
}
