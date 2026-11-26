import { PushNotifications, type ActionPerformed } from '@capacitor/push-notifications'

import { registerPushDevice } from '../api/generated/notifications/notifications'
import { Grafikomat } from './native-plugin'
import { nativePlatform } from './platform'
import { sessionToken } from './session-token'

/**
 * Push notifications in the iOS and Android apps (docs/mobile.md). After login the app asks for permission once
 * and registers the phone with the server (`POST /api/me/push-devices`); the server unpins it on logout. Every
 * notification carries the screen it is about (`path`, from the backend's `push_path`) and its company; tapping it
 * opens that screen, also when the app was closed (the plugin keeps the tap until the listener below is added).
 */
export type PushTarget = { path: string; companyId?: string }

/** Only the app's own routes: "/grafik?dzien=2026-12-04", never another site or a scheme. */
const SAFE_PATH = /^\/(?!\/)[\w\-/.%]*(\?[\w\-=&.%]*)?$/

export function pushTarget(data: unknown): PushTarget | null {
  if (!data || typeof data !== 'object') return null
  const { path, company_id: companyId } = data as Record<string, unknown>
  if (typeof path !== 'string' || !SAFE_PATH.test(path)) return null
  return { path, companyId: typeof companyId === 'string' && companyId ? companyId : undefined }
}

const CHANNEL = { id: 'grafik', name: 'Grafik i zmiany', description: 'Nowy grafik, oddane zmiany i decyzje kierownika' }

let opener: ((target: PushTarget) => void) | null = null
let waiting: PushTarget | null = null
let enabledFor: string | null = null
let registered = false

/** Listeners, once at start (before the first screen), so a tap that started the app is not lost. */
export async function setUpPush(onReceived: () => void): Promise<void> {
  const platform = nativePlatform()
  if (!platform) return
  await PushNotifications.addListener('registration', ({ value }) => {
    if (!sessionToken()) return
    void registerPushDevice({ platform, token: value }).catch(() => undefined)
  })
  await PushNotifications.addListener('registrationError', (error) => console.warn('push registration failed', error))
  await PushNotifications.addListener('pushNotificationReceived', onReceived)
  await PushNotifications.addListener('pushNotificationActionPerformed', (action: ActionPerformed) => {
    const target = pushTarget(action.notification.data)
    if (!target) return
    if (opener) opener(target)
    else waiting = target
  })
}

/** Where a tap goes (set once the router exists); a tap that came earlier is handled now. */
export function onPushOpen(open: (target: PushTarget) => void): void {
  opener = open
  if (waiting) {
    open(waiting)
    waiting = null
  }
}

/** After login: ask for permission (only the first time) and register this phone for this person. */
export async function enablePush(userId: string): Promise<void> {
  const platform = nativePlatform()
  if (!platform || enabledFor === userId) return
  enabledFor = userId
  try {
    // Without the Firebase file in the build, registering would stop the Android app.
    if (platform === 'android' && !(await Grafikomat.info()).push) return
    let permission = await PushNotifications.checkPermissions()
    if (permission.receive === 'prompt' || permission.receive === 'prompt-with-rationale') {
      permission = await PushNotifications.requestPermissions()
    }
    if (permission.receive !== 'granted') return
    if (platform === 'android') await PushNotifications.createChannel({ ...CHANNEL, importance: 4, visibility: 1 })
    await PushNotifications.register()
    registered = true
  } catch (error) {
    console.warn('push not available', error)
  }
}

/** On logout (the server unpins the phone too): no more notifications until someone logs in again. */
export async function disablePush(): Promise<void> {
  enabledFor = null
  if (!nativePlatform() || !registered) return
  registered = false
  try {
    await PushNotifications.removeAllDeliveredNotifications()
    await PushNotifications.unregister()
  } catch {
    // Logged out anyway; the server no longer sends to this phone.
  }
}
