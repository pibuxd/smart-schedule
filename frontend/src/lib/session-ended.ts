/** Set when a request found the session ended, so the login screen can say why the person is here. */
export const SESSION_ENDED_KEY = 'grafikomat.session-ended'

export function takeSessionEnded(): boolean {
  try {
    const ended = window.sessionStorage.getItem(SESSION_ENDED_KEY) === '1'
    window.sessionStorage.removeItem(SESSION_ENDED_KEY)
    return ended
  } catch {
    return false
  }
}
