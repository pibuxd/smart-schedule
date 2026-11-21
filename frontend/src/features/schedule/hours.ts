// Other hours of a shift (overtime, leaving early): small helpers shared by the employee's and the manager's screens.

const TIME = /^([01]?\d|2[0-3]):([0-5]\d)$/

/** "06:00" / "6:00" is a time of day; "" or "25:00" is not. */
export function isTime(value: string): boolean {
  return TIME.test(value.trim())
}

function minutesOfDay(value: string): number {
  const [, h, m] = TIME.exec(value.trim()) ?? []
  return Number(h) * 60 + Number(m)
}

/** Minutes from `start` to `end` (wall-clock times); an end before the start is the next day, as in the shift settings. */
export function minutesBetween(start: string, end: string): number {
  const diff = minutesOfDay(end) - minutesOfDay(start)
  return diff > 0 ? diff : diff + 24 * 60
}

/** 90 -> "1 h 30 min", 120 -> "2 h", 45 -> "45 min" (the sign is dropped). */
export function lengthText(minutes: number): string {
  const all = Math.abs(Math.round(minutes))
  const hours = Math.floor(all / 60)
  const rest = all % 60
  if (hours && rest) return `${hours} h ${rest} min`
  return hours ? `${hours} h` : `${rest} min`
}

/** +60 -> "nadgodziny: +1 h", -120 -> "krócej o 2 h", 0 -> "tyle, ile w grafiku". */
export function differenceText(minutes: number): string {
  if (minutes > 0) return `nadgodziny: +${lengthText(minutes)}`
  if (minutes < 0) return `krócej o ${lengthText(minutes)}`
  return 'tyle, ile w grafiku'
}

/** The same with a capital letter, for a line of its own. */
export function differenceSentence(minutes: number): string {
  const text = differenceText(minutes)
  return text.charAt(0).toUpperCase() + text.slice(1)
}

const pad = (value: number) => String(value).padStart(2, '0')

/** Minutes east of UTC written at the end of an ISO time ("…+01:00" → 60, "…Z" → 0), or null without one. */
function offsetMinutes(iso: string): number | null {
  if (/z$/i.test(iso)) return 0
  const match = /([+-])(\d{2}):?(\d{2})$/.exec(iso)
  if (!match) return null
  return (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3]))
}

/**
 * The wall-clock time of a moment, "HH:MM" ("Wychodzę teraz"). With `zoneOf`, a time of the location with its
 * offset (a shift's `start_at`), it is the location's clock, whatever zone the phone is in; else the phone's.
 */
export function clockTime(date: Date, zoneOf?: string): string {
  const offset = zoneOf ? offsetMinutes(zoneOf) : null
  if (offset === null) return `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const there = new Date(date.getTime() + offset * 60_000)
  return `${pad(there.getUTCHours())}:${pad(there.getUTCMinutes())}`
}
