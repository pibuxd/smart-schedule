import { useEffect, useState } from 'react'

import { useMe } from '../../api/generated/auth/auth'
import type { MeOut, MyCompanyOut } from '../../api/generated/model'
import { errorMessage, errorStatus, NETWORK_PROBLEM } from '../../lib/api-error'
import { enablePush } from '../../native/push'

const COMPANY_KEY = 'grafikomat.company'
const COMPANY_EVENT = 'grafikomat:company'

function readStoredCompany(): string | null {
  try {
    return window.localStorage.getItem(COMPANY_KEY)
  } catch {
    return null
  }
}

function storeCompany(id: string) {
  try {
    window.localStorage.setItem(COMPANY_KEY, id)
  } catch {
    // Private mode or blocked storage: the first company is used next time, which is fine.
  }
}

/** Show this company from now on (a tapped push notification is about it), also on screens already open. */
export function openCompany(id: string) {
  storeCompany(id)
  window.dispatchEvent(new CustomEvent<string>(COMPANY_EVENT, { detail: id }))
}

export type Session =
  | { state: 'loading' }
  | { state: 'logged-out' }
  | { state: 'error'; retry: () => void; message: string }
  | {
      state: 'ready'
      me: MeOut
      company: MyCompanyOut | undefined
      chooseCompany: (id: string) => void
    }

/** Who is logged in and which company the screens show (remembered on this device). */
export function useSession(): Session {
  const me = useMe({ query: { retry: false, staleTime: 60_000 } })
  const [companyId, setCompanyId] = useState<string | null>(readStoredCompany)
  useEffect(() => {
    const switchTo = (event: Event) => setCompanyId((event as CustomEvent<string>).detail)
    window.addEventListener(COMPANY_EVENT, switchTo)
    return () => window.removeEventListener(COMPANY_EVENT, switchTo)
  }, [])
  const userId = me.data?.status === 200 ? (me.data.data as MeOut).id : null
  // The iOS and Android apps register the phone for push notifications once someone is logged in (again after a
  // new login; `enablePush` does nothing when this session's phone is registered already).
  useEffect(() => {
    if (userId) void enablePush()
  }, [userId])

  if (me.isPending) return { state: 'loading' }
  if (me.isError) {
    if (errorStatus(me.error) === 401) return { state: 'logged-out' }
    return { state: 'error', retry: () => void me.refetch(), message: errorMessage(me.error, NETWORK_PROBLEM) }
  }
  const data = me.data.data as MeOut
  const company = data.companies.find((c) => c.id === companyId) ?? data.companies[0]
  return {
    state: 'ready',
    me: data,
    company,
    chooseCompany: (id: string) => {
      storeCompany(id)
      setCompanyId(id)
    },
  }
}
