import { Grafikomat } from './native-plugin'
import { nativePlatform } from './platform'

/**
 * Fill the login code from the SMS on Android: the system shows the message and asks whether to let Grafikomat
 * read it; one tap and the code is in. Typing it by hand always works too. iOS offers the code above the keyboard
 * by itself (`CodeInput` has `autocomplete="one-time-code"`), and so do browsers that support it.
 * Returns a function that stops waiting.
 */
export function listenForSmsCode(onCode: (code: string) => void): () => void {
  if (nativePlatform() !== 'android') return () => undefined
  let active = true
  Grafikomat.waitForSmsCode()
    .then(({ code }) => {
      if (active && /^\d{6}$/.test(code)) onCode(code)
    })
    .catch(() => undefined)
  return () => {
    active = false
    void Grafikomat.stopSmsCode().catch(() => undefined)
  }
}
