/**
 * Fetch wrapper used by every generated API call.
 * Sends the Django session cookie and the CSRF token, and turns HTTP errors into exceptions
 * so TanStack Query can show an error state.
 */

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

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const method = (options.method ?? 'GET').toUpperCase()
  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCookie('csrftoken')
    if (csrf) headers.set('X-CSRFToken', decodeURIComponent(csrf))
  }

  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' })
  const text = await response.text()
  const body: unknown = text ? JSON.parse(text) : undefined

  if (!response.ok) {
    throw new ApiError(response.status, body)
  }
  return { data: body, status: response.status, headers: response.headers } as T
}
