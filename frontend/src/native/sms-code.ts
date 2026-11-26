import { Grafikomat } from './native-plugin'
import { nativePlatform } from './platform'

/**
 * Fill the login code from the SMS on Android: the system shows the message and asks whether to let Grafikomat
 * read it; one tap and the code is in. Typing it by hand always works too. iOS offers the code above the keyboard
 * by itself (`CodeInput` has `autocomplete="one-time-code"`), and so do browsers that support it.
 *
 * Android offers only an SMS that comes after the waiting began, and the server sends the SMS before it answers
 * "request-code". So the wait starts before the request (`startSmsCodeWait`, also for "send again"), and the code
 * step takes the code (`listenForSmsCode`), also one that came while the request was still on its way.
 */
let wait: object | null = null
let caught: string | null = null
let taker: ((code: string) => void) | null = null

/** Right before asking the server for a code: from now on the next SMS with a code is caught. */
export function startSmsCodeWait(): void {
  if (nativePlatform() !== 'android') return
  const mine = {}
  wait = mine
  caught = null
  Grafikomat.waitForSmsCode()
    .then(({ code }) => {
      if (wait !== mine || !/^\d{6}$/.test(code)) return
      if (taker) taker(code)
      else caught = code
    })
    .catch(() => undefined)
}

/** The code was not sent after all, or the code step was left: stop waiting. */
export function stopSmsCodeWait(): void {
  caught = null
  if (!wait) return
  wait = null
  void Grafikomat.stopSmsCode().catch(() => undefined)
}

/**
 * The code step: get the code from the SMS, at once when it came already. A code step opened without a request
 * (the page was reloaded) starts waiting now. Returns a function that stops listening; leaving the step stops the
 * wait too.
 */
export function listenForSmsCode(onCode: (code: string) => void): () => void {
  if (nativePlatform() !== 'android') return () => undefined
  if (!wait) startSmsCodeWait()
  taker = onCode
  if (caught) {
    const code = caught
    caught = null
    onCode(code)
  }
  return () => {
    if (taker === onCode) taker = null
    // A step drawn again at once (React's strict mode, a new render of the screen) listens again before this runs.
    window.setTimeout(() => {
      if (!taker) stopSmsCodeWait()
    }, 0)
  }
}
