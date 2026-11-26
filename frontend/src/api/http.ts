/**
 * Fetch wrapper used by every generated API call.
 * In a browser it sends the Django session cookie and the CSRF token. In the iOS and Android apps (docs/mobile.md)
 * it calls the server's HTTPS address and sends the session key in a header instead (no cookies, so no CSRF
 * token either), keeping the key the server hands back. HTTP errors become exceptions, so TanStack Query can show
 * an error state.
 */

import { apiUrl, nativePlatform } from '../native/platform'
import { sessionToken, setSessionToken } from '../native/session-token'

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function readCookie(name: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((part) => part.startsWith(`${name}=`))
    ?.split('=')[1]
}

/** JSON from the API; anything else (an HTML error page, a proxy's "Bad Gateway") is kept out of the body. */
function parseBody(text: string): unknown {
  if (!text) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export const CLIENT_HEADER = 'X-Grafikomat-Client'
export const SESSION_HEADER = 'X-Grafikomat-Session'

/** The request as the platform sends it: cookie + CSRF token in a browser, the session key header in the apps. */
export async function send(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  const platform = nativePlatform()
  if (platform) {
    headers.set(CLIENT_HEADER, platform)
    const token = sessionToken()
    if (token) headers.set(SESSION_HEADER, token)
    const response = await fetch(apiUrl(url), { ...options, headers, credentials: 'omit' })
    const handed = response.headers.get(SESSION_HEADER)
    if (handed !== null) setSessionToken(handed || null)
    return response
  }
  const method = (options.method ?? 'GET').toUpperCase()
  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCookie('csrftoken')
    if (csrf) headers.set('X-CSRFToken', decodeURIComponent(csrf))
  }
  return fetch(url, { ...options, headers, credentials: 'same-origin' })
}

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await send(url, options)
  const text = await response.text()
  const body = parseBody(text)

  if (!response.ok) {
    throw new ApiError(response.status, body)
  }
  return { data: body, status: response.status, headers: response.headers } as T
}
