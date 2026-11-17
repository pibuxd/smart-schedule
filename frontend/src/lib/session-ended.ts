/** Set when a request found the session ended, so the login screen can say why the person is here. */
export const SESSION_ENDED_KEY = 'grafikomat.session-ended'

const ACTIVE_KEY = 'grafikomat.session-active'

export function rememberSession(active: boolean) {
  try {
    if (active) window.sessionStorage.setItem(ACTIVE_KEY, '1')
    else window.sessionStorage.removeItem(ACTIVE_KEY)
  } catch {
    // Storage is optional in private browsing.
  }
}

export function noteUnauthorized(hadSession: boolean) {
  try {
    if (hadSession || window.sessionStorage.getItem(ACTIVE_KEY)) window.sessionStorage.setItem(SESSION_ENDED_KEY, '1')
    window.sessionStorage.removeItem(ACTIVE_KEY)
  } catch {
    // Login still works without the explanatory message.
  }
}

export function takeSessionEnded(): boolean {
  try {
    const ended = window.sessionStorage.getItem(SESSION_ENDED_KEY) === '1'
    window.sessionStorage.removeItem(SESSION_ENDED_KEY)
    return ended
  } catch {
    return false
  }
}
