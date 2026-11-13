import type { VersionShiftOut } from '../../api/generated/model'
import { addDays, parseDate, toIsoDate } from '../../lib/dates'

/** One column of the schedule grid: a shift type on one position, with its usual hours. */
export type GridColumn = {
  key: string
  shiftTypeName: string
  positionName: string
  start: string
  end: string
}

export type GridRow = { date: string; cells: Record<string, VersionShiftOut[]> }

export const columnKey = (shift: VersionShiftOut) => `${shift.shift_type_name}|${shift.position_id}`

function mostCommon(values: string[]): string {
  const counts = new Map<string, number>()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] ?? ''
}

/** Days of the period in rows, shift types × positions in columns (earliest shift first). */
export function buildGrid(shifts: VersionShiftOut[], start: string, end: string): { columns: GridColumn[]; rows: GridRow[] } {
  const byColumn = new Map<string, VersionShiftOut[]>()
  for (const shift of shifts) {
    const key = columnKey(shift)
    if (!byColumn.has(key)) byColumn.set(key, [])
    byColumn.get(key)!.push(shift)
  }
  const columns: GridColumn[] = [...byColumn.entries()].map(([key, list]) => ({
    key,
    shiftTypeName: list[0].shift_type_name,
    positionName: list[0].position_name,
    start: mostCommon(list.map((s) => s.start_time)),
    end: mostCommon(list.map((s) => s.end_time)),
  }))
  // Night shifts (ending the next morning) start late, so ordering by the start time keeps the day's order.
  columns.sort((a, b) => a.start.localeCompare(b.start) || a.positionName.localeCompare(b.positionName, 'pl'))

  const rows: GridRow[] = []
  for (let day = parseDate(start); toIsoDate(day) <= end; day = addDays(day, 1)) {
    rows.push({ date: toIsoDate(day), cells: {} })
  }
  const rowByDate = new Map(rows.map((r) => [r.date, r]))
  for (const shift of shifts) {
    const row = rowByDate.get(shift.date)
    if (!row) continue
    const key = columnKey(shift)
    ;(row.cells[key] ??= []).push(shift)
  }
  return { columns, rows }
}

/** The changes for dropping the person of `from` onto `to`: a swap, or a move when `to` is empty. */
export function swapChanges(from: VersionShiftOut, to: VersionShiftOut) {
  return [
    { shift_id: to.id, employee_id: from.employee_id },
    { shift_id: from.id, employee_id: to.employee_id },
  ]
}

/** "91 %" with a Polish decimal comma. */
export const percent = (value: number) => `${Math.round(value * 10) / 10}`.replace('.', ',') + ' %'
