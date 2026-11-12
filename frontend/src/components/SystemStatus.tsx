import { useHealth } from '../api/generated/system/system'

/** Shows whether the browser can reach the API and the database. */
export function SystemStatus() {
  const { data, isPending, isError } = useHealth()

  if (isPending) {
    return <p className="mt-6 text-lg">Sprawdzam połączenie z serwerem…</p>
  }
  if (isError || data.status !== 200) {
    return (
      <p role="alert" className="mt-6 text-lg">
        Nie udało się połączyć z serwerem. Spróbuj odświeżyć stronę za chwilę.
      </p>
    )
  }
  return <p className="mt-6 text-lg">Serwer i baza danych działają.</p>
}
