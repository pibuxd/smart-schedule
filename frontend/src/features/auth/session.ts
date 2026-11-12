import { useState } from 'react'

import { useMe } from '../../api/generated/auth/auth'
import type { MeOut, MyCompanyOut } from '../../api/generated/model'
import { errorStatus } from '../../lib/api-error'

const COMPANY_KEY = 'grafikomat.company'

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

export type Session =
  | { state: 'loading' }
  | { state: 'logged-out' }
  | { state: 'error'; retry: () => void }
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

  if (me.isPending) return { state: 'loading' }
  if (me.isError) {
    if (errorStatus(me.error) === 401) return { state: 'logged-out' }
    return { state: 'error', retry: () => void me.refetch() }
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
