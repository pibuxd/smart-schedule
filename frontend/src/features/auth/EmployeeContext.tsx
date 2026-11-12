import { createContext, useContext } from 'react'

export type EmployeeContextValue = { companyId: string; readOnly: boolean }

export const EmployeeContext = createContext<EmployeeContextValue | null>(null)

export function useEmployee(): EmployeeContextValue {
  const value = useContext(EmployeeContext)
  if (!value) throw new Error('useEmployee must be used inside the employee layout')
  return value
}
