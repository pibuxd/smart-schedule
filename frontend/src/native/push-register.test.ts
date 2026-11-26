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
let session: string | null = 'session-1'

vi.mock('@capacitor/push-notifications', () => ({ PushNotifications: plugin }))
vi.mock('./platform', () => ({ nativePlatform: () => 'ios' }))
vi.mock('./native-plugin', () => ({ Grafikomat: { info: async () => ({ push: true }) } }))
vi.mock('./session-token', () => ({ sessionToken: () => session }))
vi.mock('../api/generated/notifications/notifications', () => ({ registerPushDevice }))

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
  })
  afterEach(() => vi.useRealTimers())

  it('tries again after a failed registration and stops once the server confirmed it', async () => {
    const push = await freshModule()
    vi.useFakeTimers()
    registerPushDevice.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ status: 204 })

    await push.enablePush()
    await vi.advanceTimersByTimeAsync(0)
    expect(registerPushDevice).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(registerPushDevice).toHaveBeenCalledTimes(2)

    await push.enablePush() // the same session again: nothing to send
    expect(registerPushDevice).toHaveBeenCalledTimes(2)
  })

  it('registers again for a new session of the same person', async () => {
    const push = await freshModule()
    registerPushDevice.mockResolvedValue({ status: 204 })
    await push.enablePush()
    await flush()
    expect(registerPushDevice).toHaveBeenCalledTimes(1)

    session = 'session-2' // the session ended and the same person logged in again, without restarting the app
    await push.enablePush()
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

    await push.enablePush()
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
