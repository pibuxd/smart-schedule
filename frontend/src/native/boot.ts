import { isNativeApp, nativePlatform } from './platform'
import { setUpPush } from './push'
import { loadSessionToken } from './session-token'

/**
 * Start of the iOS and Android apps, before the first screen (main.tsx). In a browser it does nothing.
 * - The screens reach under the status bar and the home indicator (viewport-fit=cover) and pad themselves with
 *   the safe areas (`html[data-native]` in index.css), so both systems look alike.
 * - The stored session key is read, so a restarted app is still logged in.
 * - Push listeners are added now, so a tap on a notification that started the app is not lost.
 */
export async function bootNativeApp(onPushReceived: () => void): Promise<void> {
  if (!isNativeApp()) return
  document.documentElement.dataset.native = nativePlatform() ?? 'app'
  const viewport = document.querySelector<HTMLMetaElement>('meta[name="viewport"]')
  if (viewport && !viewport.content.includes('viewport-fit')) viewport.content += ', viewport-fit=cover'
  await loadSessionToken()
  await setUpPush(onPushReceived)
}
