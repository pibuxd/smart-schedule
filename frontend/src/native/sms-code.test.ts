import { afterEach, describe, expect, it, vi } from 'vitest'

let resolveCode: (value: { code: string }) => void = () => undefined
const waitForSmsCode = vi.fn(() => new Promise<{ code: string }>((resolve) => (resolveCode = resolve)))
const stopSmsCode = vi.fn(async () => undefined)

vi.mock('./platform', () => ({ nativePlatform: () => 'android' }))
vi.mock('./native-plugin', () => ({ Grafikomat: { waitForSmsCode, stopSmsCode } }))

const { listenForSmsCode, startSmsCodeWait, stopSmsCodeWait } = await import('./sms-code')

describe('the code from the SMS on Android', () => {
  afterEach(() => {
    stopSmsCodeWait()
    vi.clearAllMocks()
  })

  it('is caught when the SMS comes before the server answered and the code step opened', async () => {
    startSmsCodeWait() // before "request-code"
    resolveCode({ code: '123456' }) // the SMS is faster than the answer
    await Promise.resolve()

    const onCode = vi.fn()
    listenForSmsCode(onCode)
    expect(onCode).toHaveBeenCalledWith('123456')
    expect(waitForSmsCode).toHaveBeenCalledTimes(1)
  })

  it('goes to the code step when it comes later, also after "send again"', async () => {
    startSmsCodeWait()
    const onCode = vi.fn()
    const stop = listenForSmsCode(onCode)
    startSmsCodeWait() // "Wyślij kod jeszcze raz"
    resolveCode({ code: '654321' })
    await Promise.resolve()
    expect(onCode).toHaveBeenCalledWith('654321')

    stop()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(stopSmsCode).toHaveBeenCalled() // leaving the step stops the wait
  })
})
