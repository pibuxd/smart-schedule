import { Preferences } from '@capacitor/preferences'
import { PushNotifications, type ActionPerformed } from '@capacitor/push-notifications'

import { registerPushDevice, unregisterPushDevice } from '../api/generated/notifications/notifications'
import { errorStatus } from '../lib/api-error'
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
 * server confirmed it, and for that session and that token: a new login (also of the same person after the session
 * ended) or a new token from the system registers again, and a failed try is tried again later.
 *
 * The switch on "Powiadomienia" (`PhonePushSwitch`) turns push off for the person on this phone: the server unpins
 * the phone first (`DELETE /api/me/push-devices`), and the choice is kept in the app's storage per person, so a new
 * login of that person here does not register the phone again; someone else logging in on it gets their own choice.
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
/** The session and token the server confirmed for this phone. */
let registered: { session: string; token: string } | null = null
const RETRY_FIRST_MS = 30_000
const RETRY_MAX_MS = 15 * 60_000
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryDelay = RETRY_FIRST_MS
/** The logged-in person turned push off on this phone (their choice, read once per person). */
let off = false
let choice: { person: string; loaded: Promise<void> } | null = null
/** A registration on its way to the server: turning push off waits for it, so it cannot land after the unpinning. */
let sending: Promise<unknown> | null = null
const offKey = (person: string) => `grafikomat.push-off.${person}`

/** Listeners, once at start (before the first screen), so a tap that started the app is not lost. */
export async function setUpPush(onReceived: () => void): Promise<void> {
  const platform = nativePlatform()
  if (!platform) return
  await PushNotifications.addListener('registration', ({ value }) => {
    deviceToken = value
    void sendToken()
  })
  await PushNotifications.addListener('registrationError', (error) => {
    enabled = false // the next login (or start) asks the system again
    console.warn('push registration failed', error)
  })
  await PushNotifications.addListener('pushNotificationReceived', onReceived)
  // Back from the phone's settings, where the person may have allowed the notifications refused before.
  document.addEventListener('resume', () => void registerIfAllowed())
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void registerIfAllowed()
  })
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

/** Tell the server this phone's token for the current session, unless it already confirmed this pair. */
async function sendToken(): Promise<void> {
  const platform = nativePlatform()
  const session = sessionToken()
  const token = deviceToken
  if (off || !platform || !token || !session || (registered?.session === session && registered.token === token)) return
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
  try {
    const request = registerPushDevice({ platform, token })
    sending = request.catch(() => undefined)
    await request
    // An answer about a pair that changed meanwhile confirms nothing now: the newer pair is sent on its own.
    if (!off && sessionToken() === session && deviceToken === token) {
      registered = { session, token }
      retryDelay = RETRY_FIRST_MS
    }
  } catch {
    // No network for a moment, or the server failed: try again later while this session and token last.
    if (off || sessionToken() !== session || deviceToken !== token) return
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
 * register this phone for this session. Already registered for this session, or push turned off by this person on
 * this phone: nothing happens.
 */
export async function enablePush(person: string): Promise<void> {
  if (!nativePlatform()) return
  await loadChoice(person)
  if (off) return
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

/** The person's choice on this phone, read from the app's storage once (switched to another person: theirs). */
function loadChoice(person: string): Promise<void> {
  if (choice?.person !== person) {
    const loaded = Preferences.get({ key: offKey(person) })
      .then(({ value }) => value === '1')
      .catch(() => false)
      .then((value) => {
        if (choice?.person === person) off = value
      })
    choice = { person, loaded }
  }
  return choice.loaded
}

/**
 * Allowed in the phone's settings after being refused: register now. Never asks the system itself (a dialog that
 * pauses and resumes the app would ask again and again), and does nothing for a person who turned push off here.
 */
async function registerIfAllowed(): Promise<void> {
  if (enabled || !choice) return
  await choice.loaded
  if (off) return
  try {
    if ((await PushNotifications.checkPermissions()).receive !== 'granted') return
  } catch {
    return
  }
  await enablePush(choice.person)
}

/**
 * The switch on "Powiadomienia". `available`: this build can get push at all (the Android build has the Firebase
 * file). `blocked`: the phone's settings do not allow Grafikomat's notifications (refused when asked, or switched
 * off there), so the switch cannot turn them on.
 */
export type PushSwitch = { available: false } | { available: true; on: boolean; blocked: boolean }

export async function pushSwitch(person: string): Promise<PushSwitch> {
  const platform = nativePlatform()
  if (!platform) return { available: false }
  try {
    if (platform === 'android' && !(await Grafikomat.info()).push) return { available: false }
    await loadChoice(person)
    const blocked = (await PushNotifications.checkPermissions()).receive === 'denied'
    return { available: true, on: !off && !blocked, blocked }
  } catch {
    return { available: false }
  }
}

/**
 * Turn push on or off for this person on this phone. Off: the server unpins the phone first, and only then the
 * choice is saved; when that fails (no network), push stays on and the error is thrown for the screen to show.
 * On: the phone is registered again (asking the system for permission if it never was).
 */
export async function setPush(person: string, on: boolean): Promise<PushSwitch> {
  await loadChoice(person)
  if (on) {
    off = false
    await Preferences.remove({ key: offKey(person) }).catch(() => undefined)
    await enablePush(person)
    return pushSwitch(person)
  }
  off = true
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
  retryDelay = RETRY_FIRST_MS
  await sending
  try {
    await unregisterPushDevice()
  } catch (error) {
    // 401: the session has ended, so the server sends nothing to this phone already.
    if (errorStatus(error) !== 401) {
      off = false
      void sendToken() // a registration that was waiting to be tried again goes on
      throw error
    }
  }
  registered = null
  await Preferences.set({ key: offKey(person), value: '1' }).catch(() => undefined)
  return pushSwitch(person)
}

/** After a confirmed logout (the server unpins the phone too): no more notifications until someone logs in again. */
export async function disablePush(): Promise<void> {
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
  retryDelay = RETRY_FIRST_MS
  registered = null
  choice = null
  off = false
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
