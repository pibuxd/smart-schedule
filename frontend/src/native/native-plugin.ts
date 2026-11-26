import { registerPlugin } from '@capacitor/core'

/**
 * The Android app's own small plugin (`android/app/src/main/java/pl/grafikomat/app/GrafikomatPlugin.java`).
 * iOS needs none: the code from an SMS is offered by the keyboard (`autocomplete="one-time-code"`), and push
 * works without extra checks.
 */
export interface GrafikomatPlugin {
  /** `push`: the build has the Firebase configuration (google-services.json), so push can be switched on. */
  info(): Promise<{ push: boolean }>
  /**
   * Wait for the next SMS with a code (SMS User Consent API): Android asks the person once whether the app may
   * read that one message, then the call resolves with the 6 digits. Rejects when refused or after 5 minutes.
   */
  waitForSmsCode(): Promise<{ code: string }>
  /** Stop waiting (the code was typed by hand, or the screen was left). */
  stopSmsCode(): Promise<void>
}

export const Grafikomat = registerPlugin<GrafikomatPlugin>('Grafikomat')
