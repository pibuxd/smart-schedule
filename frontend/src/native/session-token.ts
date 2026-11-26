import { Preferences } from '@capacitor/preferences'

import { isNativeApp } from './platform'

/**
 * The apps' login: the Django session key the server hands over in the `X-Grafikomat-Session` header
 * (backend `apps/core/native.py`). It is kept in the app's own storage (UserDefaults / SharedPreferences, which
 * the system does not clear like a WebView's storage), so the person stays logged in after the app restarts.
 * The web version keeps using its session cookie.
 */
const KEY = 'grafikomat.session'

let token: string | null = null

/** Read the stored key once, before the first API call (`boot.ts`). */
export async function loadSessionToken(): Promise<void> {
  if (!isNativeApp()) return
  try {
    token = (await Preferences.get({ key: KEY })).value
  } catch {
    token = null
  }
}

export function sessionToken(): string | null {
  return token
}

/** The server gave a new key (login) or an empty one (logout, ended session). */
export function setSessionToken(value: string | null): void {
  if (value === token) return
  token = value
  void (value ? Preferences.set({ key: KEY, value }) : Preferences.remove({ key: KEY })).catch(() => undefined)
}
