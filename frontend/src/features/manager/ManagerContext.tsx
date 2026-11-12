import { createContext, useContext } from 'react'

export type ManagerContextValue = { companyId: string; role: 'owner' | 'manager'; readOnly: boolean }

export const ManagerContext = createContext<ManagerContextValue | null>(null)

/** The company the manager's screens show; available inside the `/kierownik` layout. */
export function useManager(): ManagerContextValue {
  const value = useContext(ManagerContext)
  if (!value) throw new Error('useManager must be used inside the manager layout')
  return value
}

export const isManagerRole = (role: string): role is 'owner' | 'manager' => role === 'owner' || role === 'manager'
