import { createFileRoute } from '@tanstack/react-router'

import { useEmployee } from '../../features/auth/EmployeeContext'
import { AvailabilityScreen } from '../../features/availability/AvailabilityScreen'

export const Route = createFileRoute('/_pracownik/kiedy-moge')({
  component: AvailabilityPage,
})

function AvailabilityPage() {
  const { companyId, readOnly } = useEmployee()
  return <AvailabilityScreen companyId={companyId} readOnly={readOnly} />
}
