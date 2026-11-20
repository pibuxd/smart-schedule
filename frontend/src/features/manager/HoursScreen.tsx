import { ChevronLeft, ChevronRight, Download } from 'lucide-react'
import { useState } from 'react'

import type { HoursReportOut } from '../../api/generated/model'
import { getHoursReportCsvUrl, useHoursReport } from '../../api/generated/reports/reports'
import { Button } from '../../components/ui/button'
import { EmptyState, ErrorState, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import { monthName } from '../../lib/dates'
import { useManager } from './ManagerContext'
import { ChangeHours, HoursReports } from './WorkedHours'

function shiftMonth(month: string, by: number): string {
  const [year, m] = month.split('-').map(Number)
  const date = new Date(year, m - 1 + by, 1)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

const hours = (value: number) => value.toLocaleString('pl-PL', { maximumFractionDigits: 2 })

/** Hours of published shifts in a month, per person and location, and the CSV for payroll. */
export function HoursScreen({ today = new Date() }: { today?: Date }) {
  const { companyId } = useManager()
  const [month, setMonth] = useState(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`)
  const report = useHoursReport({ company_id: companyId, month })

  return (
    <div className="grid gap-6">
      <HoursReports />
      <ChangeHours />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="m-0 text-2xl font-extrabold">Godziny w miesiącu</h1>
          <p className="m-0 max-w-[62ch] text-ink-muted">
            Zmiany z opublikowanych grafików, z zatwierdzonymi nadgodzinami i krótszymi zmianami. Ktoś zamienił się poza
            aplikacją? Popraw ten dzień w grafiku i opublikuj.
          </p>
        </div>
        <a
          href={getHoursReportCsvUrl({ company_id: companyId, month })}
          download
          className="inline-flex min-h-(--touch) items-center gap-2 rounded-md border-2 border-accent bg-surface px-5 font-semibold text-accent hover:bg-accent-soft"
        >
          <Download aria-hidden="true" size={20} />
          Pobierz plik CSV
        </a>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="quiet" size="normal" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Poprzedni miesiąc">
          <ChevronLeft aria-hidden="true" size={22} />
        </Button>
        <h2 className="m-0 min-w-48 text-center text-xl font-extrabold">{monthName(month)}</h2>
        <Button variant="quiet" size="normal" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Następny miesiąc">
          <ChevronRight aria-hidden="true" size={22} />
        </Button>
      </div>
      {report.isPending ? (
        <Loading>Liczę godziny…</Loading>
      ) : report.isError ? (
        <ErrorState onRetry={() => void report.refetch()}>
          {errorMessage(report.error, 'Nie udało się policzyć godzin. Spróbuj jeszcze raz.')}
        </ErrorState>
      ) : (
        <HoursTable data={report.data.data as HoursReportOut} onShowMonth={setMonth} />
      )}
    </div>
  )
}

function HoursTable({ data, onShowMonth }: { data: HoursReportOut; onShowMonth: (month: string) => void }) {
  if (data.rows.length === 0) {
    const latest = data.latest_month && data.latest_month !== data.month ? data.latest_month : null
    return (
      <EmptyState title="W tym miesiącu nie ma opublikowanych zmian">
        <p className="m-0">Godziny pojawią się tutaj, gdy opublikujesz grafik na ten miesiąc.</p>
        {latest && (
          <div>
            <Button variant="secondary" size="normal" onClick={() => onShowMonth(latest)}>
              Pokaż ostatni miesiąc z godzinami: {monthName(latest)}
            </Button>
          </div>
        )}
      </EmptyState>
    )
  }
  const many = data.locations.length > 1
  // Only when someone worked other hours than the schedule says, so the usual table stays short.
  const other = data.rows.some((row) => (row.longer ?? 0) > 0 || (row.shorter ?? 0) > 0)
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-surface">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b-2 border-ink">
            <th className="px-3 py-2">Osoba</th>
            <th className="px-3 py-2 text-right">Zmiany</th>
            {many && data.locations.map((l) => <th key={l.id} className="px-3 py-2 text-right">{l.name}</th>)}
            {other && (
              <>
                <th className="px-3 py-2 text-right">Nadgodziny</th>
                <th className="px-3 py-2 text-right">Krócej</th>
              </>
            )}
            <th className="px-3 py-2 text-right">Razem godzin</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => {
            const by = new Map(row.by_location.map((h) => [h.location_id, h.hours]))
            return (
              <tr key={row.employee_id} className="border-b border-grid">
                <td className="px-3 py-2">
                  <span className="font-semibold">{row.name}</span>
                  <span className="block text-sm text-ink-muted">{row.home_location_name}</span>
                  {row.elsewhere && (
                    <span className="block text-sm font-semibold text-prefer-not">
                      Pracuje też w lokalach, których nie prowadzisz, więc suma jest niepełna.
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{row.shifts}</td>
                {many &&
                  data.locations.map((l) => (
                    <td key={l.id} className="px-3 py-2 text-right tabular-nums">
                      {by.has(l.id) ? hours(by.get(l.id)!) : '–'}
                    </td>
                  ))}
                {other && (
                  <>
                    <td className="px-3 py-2 text-right tabular-nums">{row.longer ? `+${hours(row.longer)}` : '–'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.shorter ? `−${hours(row.shorter)}` : '–'}</td>
                  </>
                )}
                <td className="px-3 py-2 text-right font-semibold tabular-nums">{hours(row.total)}</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-ink">
            <td
              className="px-3 py-2 font-extrabold"
              colSpan={2 + (many ? data.locations.length : 0) + (other ? 2 : 0)}
            >
              Razem
            </td>
            <td className="px-3 py-2 text-right font-extrabold tabular-nums">{hours(data.total)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
