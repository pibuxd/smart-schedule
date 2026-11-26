import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const platform = vi.hoisted(() => ({ current: null as 'ios' | 'android' | null }))
const stored = vi.hoisted(() => new Map<string, string>())

vi.mock('@capacitor/core', () => ({ Capacitor: { getPlatform: () => platform.current ?? 'web' } }))
vi.mock('@capacitor/preferences', () => ({
  Preferences: {
    get: async ({ key }: { key: string }) => ({ value: stored.get(key) ?? null }),
    set: async ({ key, value }: { key: string; value: string }) => void stored.set(key, value),
    remove: async ({ key }: { key: string }) => void stored.delete(key),
  },
}))

import { loadSessionToken, sessionToken, setSessionToken } from '../native/session-token'
import { apiFetch } from './http'

function answer(headers: Record<string, string> = {}, status = 200) {
  return vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ ok: true }), { status, headers }))
}

describe('apiFetch', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_ORIGIN', 'https://grafikomat.test/')
  })
  afterEach(() => {
    platform.current = null
    setSessionToken(null)
    stored.clear()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('in a browser sends the CSRF cookie back and calls its own /api', async () => {
    document.cookie = 'csrftoken=abc%3D'
    const fetchMock = answer()
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/api/auth/logout', { method: 'POST' })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/auth/logout')
    expect(init.credentials).toBe('same-origin')
    const headers = new Headers(init.headers)
    expect(headers.get('X-CSRFToken')).toBe('abc=')
    expect(headers.get('X-Grafikomat-Client')).toBeNull()
  })

  it('in the app calls the server over HTTPS with the session key and keeps the key it is given', async () => {
    platform.current = 'ios'
    stored.set('grafikomat.session', 'old-key')
    await loadSessionToken()
    const fetchMock = answer({ 'X-Grafikomat-Session': 'new-key' })
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/api/auth/verify-code', { method: 'POST' })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('https://grafikomat.test/api/auth/verify-code')
    expect(init.credentials).toBe('omit')
    const headers = new Headers(init.headers)
    expect(headers.get('X-Grafikomat-Client')).toBe('ios')
    expect(headers.get('X-Grafikomat-Session')).toBe('old-key')
    expect(headers.get('X-CSRFToken')).toBeNull()
    expect(sessionToken()).toBe('new-key')
    await vi.waitFor(() => expect(stored.get('grafikomat.session')).toBe('new-key'))
  })

  it('in the app forgets the key when the server empties it (logout, ended session)', async () => {
    platform.current = 'android'
    setSessionToken('key')
    vi.stubGlobal('fetch', answer({ 'X-Grafikomat-Session': '' }, 401))

    await expect(apiFetch('/api/me')).rejects.toMatchObject({ status: 401 })

    expect(sessionToken()).toBeNull()
    await vi.waitFor(() => expect(stored.has('grafikomat.session')).toBe(false))
  })
})
