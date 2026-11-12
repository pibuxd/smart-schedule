import type { ReactNode } from 'react'

import { ManagerContext } from './ManagerContext'

/** Manager screens read the company from the layout; tests wrap them the same way. */
export function AsManager({ children, readOnly = false }: { children: ReactNode; readOnly?: boolean }) {
  return <ManagerContext.Provider value={{ companyId: 'c1', role: 'owner', readOnly }}>{children}</ManagerContext.Provider>
}
