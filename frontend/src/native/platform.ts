import { Capacitor } from '@capacitor/core'

/**
 * The iOS and Android apps (Capacitor, docs/mobile.md) run this same SPA from their own origin. In a browser
 * everything below is off and the app works as before.
 */
export type NativePlatform = 'ios' | 'android'

export function nativePlatform(): NativePlatform | null {
  const platform = Capacitor.getPlatform()
  return platform === 'ios' || platform === 'android' ? platform : null
}

export const isNativeApp = (): boolean => nativePlatform() !== null

/**
 * Where the apps find the API: the server's HTTPS address, fixed when the app is built
 * (`VITE_API_ORIGIN`, e.g. "https://grafikomat.pl"). The web version calls `/api` on its own domain.
 */
export function apiOrigin(): string {
  return (import.meta.env.VITE_API_ORIGIN ?? '').replace(/\/+$/, '')
}

/** A path of the API ("/api/me") as the current platform must call it. */
export function apiUrl(path: string): string {
  return isNativeApp() ? `${apiOrigin()}${path}` : path
}
