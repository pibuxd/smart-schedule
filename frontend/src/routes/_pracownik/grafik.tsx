import { createFileRoute } from '@tanstack/react-router'

import { useEmployee } from '../../features/auth/EmployeeContext'
import { MyScheduleScreen } from '../../features/schedule/MyScheduleScreen'

export const Route = createFileRoute('/_pracownik/grafik')({
  component: MySchedulePage,
})

function MySchedulePage() {
  const { companyId } = useEmployee()
  return (
    <div className="grid gap-4">
      <h1 className="m-0 text-xl font-extrabold">Mój grafik</h1>
      <MyScheduleScreen companyId={companyId} />
    </div>
  )
}
