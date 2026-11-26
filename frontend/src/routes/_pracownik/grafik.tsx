import { createFileRoute } from '@tanstack/react-router'

import { useEmployee } from '../../features/auth/EmployeeContext'
import { MyScheduleScreen } from '../../features/schedule/MyScheduleScreen'
import { searchDay, searchId } from '../../lib/focus'

export const Route = createFileRoute('/_pracownik/grafik')({
  // From a push notification: ?dzien=2026-12-04 shows that day's shift (or a new schedule from its first day),
  // ?oferta=<id> a shift someone gives away that I could take.
  validateSearch: (search: Record<string, unknown>): { dzien?: string; oferta?: string } => ({
    dzien: searchDay(search.dzien),
    oferta: searchId(search.oferta),
  }),
  component: MySchedulePage,
})

function MySchedulePage() {
  const { companyId, readOnly } = useEmployee()
  const { dzien, oferta } = Route.useSearch()
  return (
    <div className="grid gap-4">
      <h1 className="m-0 text-xl font-extrabold">Mój grafik</h1>
      <MyScheduleScreen
        key={`${dzien ?? ''}/${oferta ?? ''}`}
        companyId={companyId}
        readOnly={readOnly}
        focusDay={dzien}
        focusOffer={oferta}
      />
    </div>
  )
}
