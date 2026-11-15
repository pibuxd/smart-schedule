import { ApiError } from '../api/http'

/**
 * The Polish message the API sent (`{"detail": ...}`). When the server answered without one (a crash, a proxy error),
 * the problem is on our side, so the user is not sent to check the internet. The fallback is for network problems.
 */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: unknown } | undefined
    if (body && typeof body.detail === 'string') return body.detail
    if (error.status >= 500) return serverProblem(fallback)
  }
  return fallback
}

/** "Nie udało się wczytać grafiku. Sprawdź internet…" becomes "Nie udało się wczytać grafiku. <our fault>". */
function serverProblem(fallback: string): string {
  if (fallback.startsWith('Nie udało się połączyć')) return SERVER_PROBLEM
  const end = fallback.indexOf('. ')
  return end > 0 ? `${fallback.slice(0, end + 1)} ${SERVER_PROBLEM}` : SERVER_PROBLEM
}

export function errorStatus(error: unknown): number | undefined {
  return error instanceof ApiError ? error.status : undefined
}

export const NETWORK_PROBLEM = 'Nie udało się połączyć z serwerem. Sprawdź internet i spróbuj jeszcze raz.'

export const SERVER_PROBLEM = 'To błąd po naszej stronie, nie Twojego internetu. Spróbuj za chwilę jeszcze raz.'
