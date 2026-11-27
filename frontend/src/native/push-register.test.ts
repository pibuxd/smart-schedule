import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Listener = (event: never) => void

const listeners: Record<string, Listener> = {}
const plugin = {
  addListener: vi.fn(async (name: string, listener: Listener) => {
    listeners[name] = listener
  }),
  checkPermissions: vi.fn(async () => ({ receive: 'granted' })),
  requestPermissions: vi.fn(async () => ({ receive: 'granted' })),
  register: vi.fn(async () => (listeners.registration as (e: { value: string }) => void)({ value: 'apns-token' })),
  unregister: vi.fn(async () => undefined),
  removeAllDeliveredNotifications: vi.fn(async () => undefined),
  createChannel: vi.fn(async () => undefined),
}
const registerPushDevice = vi.fn()
const unregisterPushDevice = vi.fn()
let session: string | null = 'session-1'
const stored = new Map<string, string>()
const preferences = {
  get: vi.fn(async ({ key }: { key: string }) => ({ value: stored.get(key) ?? null })),
  set: vi.fn(async ({ key, value }: { key: string; value: string }) => void stored.set(key, value)),
  remove: vi.fn(async ({ key }: { key: string }) => void stored.delete(key)),
}

vi.mock('@capacitor/push-notifications', () => ({ PushNotifications: plugin }))
vi.mock('./platform', () => ({ nativePlatform: () => 'ios' }))
vi.mock('./native-plugin', () => ({ Grafikomat: { info: async () => ({ push: true }) } }))
vi.mock('./session-token', () => ({ sessionToken: () => session }))
vi.mock('@capacitor/preferences', () => ({ Preferences: preferences }))
vi.mock('../api/generated/notifications/notifications', () => ({ registerPushDevice, unregisterPushDevice }))

async function freshModule() {
  vi.resetModules()
  const push = await import('./push')
  await push.setUpPush(() => undefined)
  return push
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('registering the phone for push', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    session = 'session-1'
    stored.clear()
    plugin.checkPermissions.mockResolvedValue({ receive: 'granted' })
  })
  afterEach(() => vi.useRealTimers())

  it('tries again after a failed registration and stops once the server confirmed it', async () => {
    const push = await freshModule()
    vi.useFakeTimers()
    registerPushDevice.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ status: 204 })

    await push.enablePush('p1')
    await vi.advanceTimersByTimeAsync(0)
    expect(registerPushDevice).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(registerPushDevice).toHaveBeenCalledTimes(2)

    await push.enablePush('p1') // the same session again: nothing to send
    expect(registerPushDevice).toHaveBeenCalledTimes(2)
  })

  it('registers again for a new session of the same person', async () => {
    const push = await freshModule()
    registerPushDevice.mockResolvedValue({ status: 204 })
    await push.enablePush('p1')
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(1)

    session = 'session-2' // the session ended and the same person logged in again, without restarting the app
    await push.enablePush('p1')
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(2)
    expect(plugin.requestPermissions).not.toHaveBeenCalled()
  })

  it('confirms a token only for the token that was sent, so a new token is still sent after a failure', async () => {
    const push = await freshModule()
    vi.useFakeTimers()
    let confirmOld: (value: unknown) => void = () => undefined
    registerPushDevice
      .mockImplementationOnce(() => new Promise((resolve) => (confirmOld = resolve))) // the first token, slow
      .mockRejectedValueOnce(new Error('offline')) // the system's new token fails to reach the server
      .mockResolvedValue({ status: 204 })

    await push.enablePush('p1')
    await vi.advanceTimersByTimeAsync(0)
    const registration = listeners.registration as (event: { value: string }) => void
    registration({ value: 'apns-token-2' }) // the system replaced the token while the first request was on its way
    await vi.advanceTimersByTimeAsync(0)
    confirmOld({ status: 204 }) // the server confirms the old token only now
    await vi.advanceTimersByTimeAsync(0)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(registerPushDevice).toHaveBeenCalledTimes(3)
    expect(registerPushDevice).toHaveBeenLastCalledWith({ platform: 'ios', token: 'apns-token-2' })
  })

  it('opens a tap handed over twice only once', async () => {
    const push = await freshModule()
    const open = vi.fn()
    push.onPushOpen(open)
    const tap = { actionId: 'tap', notification: { id: 'n1', data: { path: '/grafik?dzien=2026-12-04' } } }
    const performed = listeners.pushNotificationActionPerformed as (event: typeof tap) => void
    performed(tap)
    performed(tap)
    expect(open).toHaveBeenCalledTimes(1)
  })
})

describe('the switch on "Powiadomienia"', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    session = 'session-1'
    stored.clear()
    plugin.checkPermissions.mockResolvedValue({ receive: 'granted' })
    registerPushDevice.mockResolvedValue({ status: 204 })
    unregisterPushDevice.mockResolvedValue({ status: 204 })
  })

  it('turns push off on the server and keeps it off for that person after a new login', async () => {
    const push = await freshModule()
    await push.enablePush('p1')
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(1)
    expect(await push.pushSwitch('p1')).toEqual({ available: true, on: true, blocked: false })

    expect(await push.setPush('p1', false)).toEqual({ available: true, on: false, blocked: false })
    expect(unregisterPushDevice).toHaveBeenCalledTimes(1)

    // Log out and in again (also after the app restarts): the choice is read from the app's storage.
    await push.disablePush()
    const restarted = await freshModule()
    session = 'session-2'
    await restarted.enablePush('p1')
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(1)
    expect(await restarted.pushSwitch('p1')).toEqual({ available: true, on: false, blocked: false })

    // Someone else logs in on this phone: their own choice, on by default.
    await restarted.disablePush()
    session = 'session-3'
    await restarted.enablePush('p2')
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(2)
  })

  it('registers the phone again when turned back on', async () => {
    const push = await freshModule()
    await push.enablePush('p1')
    await flush()
    await push.setPush('p1', false)

    expect(await push.setPush('p1', true)).toEqual({ available: true, on: true, blocked: false })
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(2)
    expect(stored.size).toBe(0)
  })

  it('stays on when the server could not be told', async () => {
    const push = await freshModule()
    await push.enablePush('p1')
    await flush()
    unregisterPushDevice.mockRejectedValueOnce(new Error('offline'))

    await expect(push.setPush('p1', false)).rejects.toThrow('offline')
    expect(await push.pushSwitch('p1')).toEqual({ available: true, on: true, blocked: false })
    expect(stored.size).toBe(0)
  })

  it('waits for a registration on its way, so it cannot land after the phone was unpinned', async () => {
    const push = await freshModule()
    const order: string[] = []
    let confirm: (value: unknown) => void = () => undefined
    registerPushDevice.mockImplementationOnce(() => new Promise((resolve) => (confirm = resolve)).then(() => order.push('register')))
    unregisterPushDevice.mockImplementationOnce(async () => order.push('unregister'))

    await push.enablePush('p1')
    const turningOff = push.setPush('p1', false)
    await flush()
    expect(unregisterPushDevice).not.toHaveBeenCalled()
    confirm({ status: 204 })
    await turningOff
    expect(order).toEqual(['register', 'unregister'])
  })

  it('cannot be turned on while the phone blocks the notifications', async () => {
    const push = await freshModule()
    plugin.checkPermissions.mockResolvedValue({ receive: 'denied' })
    await push.enablePush('p1')
    expect(await push.pushSwitch('p1')).toEqual({ available: true, on: false, blocked: true })
    expect(registerPushDevice).not.toHaveBeenCalled()

    // Allowed in the phone's settings: back in the app, the phone is registered without asking again.
    plugin.checkPermissions.mockResolvedValue({ receive: 'granted' })
    document.dispatchEvent(new Event('resume'))
    await flush()
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(1)
    expect(plugin.requestPermissions).not.toHaveBeenCalled()
  })
})
