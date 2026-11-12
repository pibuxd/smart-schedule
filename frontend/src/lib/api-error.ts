import { ApiError } from '../api/http'

/** The Polish message the API sent (`{"detail": ...}`), or a fallback for network problems. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: unknown } | undefined
    if (body && typeof body.detail === 'string') return body.detail
  }
  return fallback
}

export function errorStatus(error: unknown): number | undefined {
  return error instanceof ApiError ? error.status : undefined
}

export const NETWORK_PROBLEM = 'Nie udało się połączyć z serwerem. Sprawdź internet i spróbuj jeszcze raz.'
