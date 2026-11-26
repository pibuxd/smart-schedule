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
 *
 * The server ties a phone to the session it registered from, so the app remembers a registration only once the
 * server confirmed it, and for that session: a new login (also of the same person after the session ended)
 * registers again, and a failed try is tried again later.
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
const tapped = new Set<string>()
/** The phone asked the system for push (permission given, `register()` done) in this run of the app. */
let enabled = false
let enabling: Promise<void> | null = null
/** The phone's token from Apple or Google, once the system gave it. */
let deviceToken: string | null = null
/** The session the server confirmed this phone for. */
let registeredSession: string | null = null
const RETRY_FIRST_MS = 30_000
const RETRY_MAX_MS = 15 * 60_000
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryDelay = RETRY_FIRST_MS

/** Listeners, once at start (before the first screen), so a tap that started the app is not lost. */
export async function setUpPush(onReceived: () => void): Promise<void> {
  const platform = nativePlatform()
  if (!platform) return
  await PushNotifications.addListener('registration', ({ value }) => {
    deviceToken = value
    registeredSession = null
    void sendToken()
  })
  await PushNotifications.addListener('registrationError', (error) => {
    enabled = false // the next login (or start) asks the system again
    console.warn('push registration failed', error)
  })
  await PushNotifications.addListener('pushNotificationReceived', onReceived)
  await PushNotifications.addListener('pushNotificationActionPerformed', (action: ActionPerformed) => {
    // iOS may hand over the tap that started the app twice (AppDelegate's and SceneDelegate's way): open it once.
    const id = action.notification.id
    if (id) {
      if (tapped.has(id)) return
      tapped.add(id)
    }
    const target = pushTarget(action.notification.data)
    if (!target) return
    if (opener) opener(target)
    else waiting = target
  })
}

/** Tell the server this phone's token for the current session, unless it already confirmed it. */
async function sendToken(): Promise<void> {
  const platform = nativePlatform()
  const session = sessionToken()
  if (!platform || !deviceToken || !session || registeredSession === session) return
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
  try {
    await registerPushDevice({ platform, token: deviceToken })
    if (sessionToken() === session) registeredSession = session
    retryDelay = RETRY_FIRST_MS
  } catch {
    // No network for a moment, or the server failed: try again later while this session lasts.
    if (sessionToken() !== session) return
    retryTimer = setTimeout(() => void sendToken(), retryDelay)
    retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS)
  }
}

/** Where a tap goes (set once the router exists); a tap that came earlier is handled now. */
export function onPushOpen(open: (target: PushTarget) => void): void {
  opener = open
  if (waiting) {
    open(waiting)
    waiting = null
  }
}

/**
 * After login (and whenever the logged-in person is known again): ask for permission (only the first time) and
 * register this phone for this session. Already registered for this session: nothing happens.
 */
export async function enablePush(): Promise<void> {
  if (!nativePlatform()) return
  if (enabled) return sendToken()
  enabling ??= askSystem().finally(() => {
    enabling = null
  })
  return enabling
}

async function askSystem(): Promise<void> {
  const platform = nativePlatform()
  try {
    // Without the Firebase file in the build, registering would stop the Android app.
    if (platform === 'android' && !(await Grafikomat.info()).push) return
    let permission = await PushNotifications.checkPermissions()
    if (permission.receive === 'prompt' || permission.receive === 'prompt-with-rationale') {
      permission = await PushNotifications.requestPermissions()
    }
    if (permission.receive !== 'granted') return
    if (platform === 'android') await PushNotifications.createChannel({ ...CHANNEL, importance: 4, visibility: 1 })
    // The token comes in the 'registration' event, which sends it to the server.
    await PushNotifications.register()
    enabled = true
  } catch (error) {
    console.warn('push not available', error)
  }
}

/** After a confirmed logout (the server unpins the phone too): no more notifications until someone logs in again. */
export async function disablePush(): Promise<void> {
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
  retryDelay = RETRY_FIRST_MS
  registeredSession = null
  if (!nativePlatform() || !enabled) return
  enabled = false
  deviceToken = null
  try {
    await PushNotifications.removeAllDeliveredNotifications()
    await PushNotifications.unregister()
  } catch {
    // Logged out anyway; the server no longer sends to this phone.
  }
}
