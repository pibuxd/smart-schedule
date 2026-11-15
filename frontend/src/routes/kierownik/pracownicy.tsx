import { createFileRoute } from '@tanstack/react-router'

import { CompanyEmployeesScreen } from '../../features/manager/CompanyEmployeesScreen'

export const Route = createFileRoute('/kierownik/pracownicy')({
  component: () => <CompanyEmployeesScreen />,
})
