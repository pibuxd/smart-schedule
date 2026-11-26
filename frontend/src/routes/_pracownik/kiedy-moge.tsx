import { createFileRoute } from '@tanstack/react-router'

import { useEmployee } from '../../features/auth/EmployeeContext'
import { AvailabilityScreen } from '../../features/availability/AvailabilityScreen'

export const Route = createFileRoute('/_pracownik/kiedy-moge')({
  // ?miesiac=2026-12: the month to open on (a notification about that month's availability links here).
  validateSearch: (search: Record<string, unknown>): { miesiac?: string } => ({
    miesiac: typeof search.miesiac === 'string' && /^\d{4}-\d{2}$/.test(search.miesiac) ? search.miesiac : undefined,
  }),
  component: AvailabilityPage,
})

function AvailabilityPage() {
  const { companyId, readOnly } = useEmployee()
  const { miesiac } = Route.useSearch()
  return <AvailabilityScreen key={miesiac} companyId={companyId} readOnly={readOnly} month={miesiac} />
}
