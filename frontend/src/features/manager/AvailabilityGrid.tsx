import { Clock } from 'lucide-react'

import type { AvailabilityGridOut, GridDayOut, GridEmployeeOut } from '../../api/generated/model'
import { Tag } from '../../components/ui/field'
import { cn } from '../../lib/cn'
import { addDays, compactTime, dayTitle, parseDate, toIsoDate, weekdayIndex, weekdayShort } from '../../lib/dates'
import { STATE_LABEL } from '../availability/marks'
import { StateIcon } from '../availability/StateIcon'

function periodDays(start: string, end: string): string[] {
  const days = []
  for (let day = parseDate(start); day <= parseDate(end); day = addDays(day, 1)) days.push(toIsoDate(day))
  return days
}

function hoursOf(day: GridDayOut): string | null {
  if (!day.from_time || !day.to_time) return null
  return `${compactTime(day.from_time.slice(0, 5))}–${compactTime(day.to_time.slice(0, 5))}`
}

function cellLabel(iso: string, day: GridDayOut | undefined): string {
  const title = dayTitle(parseDate(iso))
  if (!day) return `${title}: mogę`
  const hours = hoursOf(day)
  const what = STATE_LABEL[day.state].toLowerCase()
  return `${title}: ${what}${hours ? ` ${hours}` : ''}${day.late ? ', zmienione po terminie' : ''}`
}

/** Legend: the same colour + sign + pattern as on the employee's calendar, and the "after the deadline" mark. */
export function GridLegend() {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-2 p-0 text-sm">
      {(['cannot', 'neutral', 'prefer'] as const).map((state) => (
        <li key={state} className="flex items-center gap-1.5">
          <span className={cn('grid size-7 place-items-center rounded-sm border-2', `avail-${state}`)}>
            <StateIcon state={state} size={16} />
          </span>
          {STATE_LABEL[state]}
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span className="relative grid size-7 place-items-center rounded-sm border-2 border-line bg-surface outline-2 outline-offset-1 outline-accent">
          <Clock aria-hidden="true" size={14} className="text-accent" />
        </span>
        Zmienione po terminie
      </li>
    </ul>
  )
}

/**
 * Employees × days. The table scrolls sideways inside its own box (a month has 31 columns); the names stay in view.
 * Hours are written in the cell, so a day marked "chętnie 6–14" is not read as the whole day.
 */
export function AvailabilityGrid({ data }: { data: AvailabilityGridOut }) {
  const days = periodDays(data.period.start, data.period.end)
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-surface" tabIndex={0} aria-label="Siatka dyspozycji">
      <table className="border-separate border-spacing-0 text-sm">
        <caption className="sr-only">Dyspozycje pracowników na każdy dzień okresu</caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky left-0 z-10 min-w-44 border-r border-b border-line bg-surface px-3 py-2 text-left align-bottom"
            >
              Pracownik
            </th>
            {days.map((iso) => {
              const day = parseDate(iso)
              const weekend = weekdayIndex(day) >= 5
              return (
                <th
                  key={iso}
                  scope="col"
                  className={cn('min-w-11 border-b border-line px-0.5 py-1.5 text-center font-semibold', weekend && 'bg-grid')}
                >
                  <span className="block text-xs font-normal text-ink-muted">{weekdayShort(day)}</span>
                  <span className="block text-base tabular-nums">{day.getDate()}</span>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {data.employees.map((employee) => (
            <Row key={employee.id} employee={employee} days={days} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Row({ employee, days }: { employee: GridEmployeeOut; days: string[] }) {
  const marks = new Map(employee.days.map((d) => [d.date, d]))
  return (
    <tr>
      <th scope="row" className="sticky left-0 z-10 border-r border-b border-line bg-surface px-3 py-1.5 text-left font-normal">
        <span className="block font-semibold">{employee.name}</span>
        <span className="flex flex-wrap items-center gap-1">
          {employee.positions.length > 0 && <span className="text-xs text-ink-muted">{employee.positions.join(', ')}</span>}
          {!employee.submitted_at && <Tag tone="warn">Nie wysłano</Tag>}
        </span>
      </th>
      {days.map((iso) => {
        const day = marks.get(iso)
        const hours = day ? hoursOf(day) : null
        const weekend = weekdayIndex(parseDate(iso)) >= 5
        return (
          <td key={iso} className={cn('border-b border-line p-0.5', weekend && 'bg-grid')}>
            <div
              role="img"
              aria-label={cellLabel(iso, day)}
              title={cellLabel(iso, day)}
              className={cn(
                'relative grid min-h-11 place-items-center content-center gap-0.5 rounded-sm border-2 px-0.5',
                `avail-${day?.state ?? 'neutral'}`,
                day?.late && 'outline-2 outline-offset-1 outline-accent',
              )}
            >
              {day && day.state !== 'neutral' && <StateIcon state={day.state} size={hours ? 14 : 18} />}
              {hours && <span className="text-cell font-semibold whitespace-nowrap tabular-nums">{hours}</span>}
              {day?.late && (
                <Clock aria-hidden="true" size={12} className="absolute -top-1.5 -right-1.5 rounded-full bg-surface text-accent" />
              )}
            </div>
          </td>
        )
      })}
    </tr>
  )
}
