import { useEffect, useState } from 'react'

import { useMe } from '../../api/generated/auth/auth'
import type { MeOut } from '../../api/generated/model'
import { Switch } from '../../components/ui/switch'
import { InlineError } from '../../components/ui/status'
import { isNativeApp } from '../../native/platform'
import { pushSwitch, setPush, type PushSwitch } from '../../native/push'

/**
 * "Na tym telefonie" on "Powiadomienia", only in the iOS and Android apps: turns push notifications off (and on
 * again) for the logged-in person on this phone. Off means the server stops sending them (`DELETE
 * /me/push-devices`); the list in the app stays as it is. Hidden on the web and in a build without push.
 */
export function PhonePushSwitch() {
  const me = useMe({ query: { retry: false, staleTime: 60_000 } })
  const person = me.data?.status === 200 ? (me.data.data as MeOut).id : null
  const [state, setState] = useState<PushSwitch | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!person || !isNativeApp()) return
    let live = true
    const read = () => void pushSwitch(person).then((next) => live && setState(next))
    // Back from the phone's settings, where the notifications may have been allowed or blocked.
    const onVisible = () => {
      if (document.visibilityState === 'visible') read()
    }
    read()
    document.addEventListener('resume', read)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      live = false
      document.removeEventListener('resume', read)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [person])

  if (!person || !state?.available) return null

  const turn = (on: boolean) => {
    setBusy(true)
    setFailed(false)
    setPush(person, on)
      .then(setState)
      .catch(() => setFailed(true))
      .finally(() => setBusy(false))
  }

  return (
    <div className="grid gap-2">
      <Switch
        label="Na tym telefonie"
        checked={state.on}
        disabled={busy || state.blocked}
        onCheckedChange={turn}
        className="rounded-lg border border-line bg-surface px-4 py-1.5"
      />
      {state.blocked && <p className="m-0 text-sm text-ink-muted">Zezwól na powiadomienia w ustawieniach telefonu.</p>}
      {failed && <InlineError>Nie udało się wyłączyć. Sprawdź internet i spróbuj jeszcze raz.</InlineError>}
    </div>
  )
}
