import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { cn } from '../../lib/cn'
import { dayTitle, parseDate, shortTime } from '../../lib/dates'
import { type AvailabilityState, type Mark, overnight } from './marks'
import { StatePicker } from './StatePicker'

// Every half hour; "00:00" as an end means midnight.
const TIMES = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`)

function timeLabel(value: string, asEnd: boolean) {
  return asEnd && value === '00:00' ? '0:00 (północ)' : shortTime(value)
}

/**
 * One day in detail: the state and, if needed, the hours.
 * "Chętnie"/"Obojętnie" with hours = "I can only then"; "Nie mogę"/"Wolę nie" with hours = "not then".
 */
export function DayHoursSheet({
  date,
  mark,
  onClose,
  onSave,
}: {
  date: string
  mark: Mark
  onClose: () => void
  onSave: (mark: Mark) => void
}) {
  const [state, setState] = useState<AvailabilityState>(mark.state)
  const [limited, setLimited] = useState(mark.from !== null || mark.to !== null)
  const [from, setFrom] = useState(mark.from ?? '14:00')
  const [to, setTo] = useState(mark.to ?? '22:00')
  const restricting = state === 'cannot' || state === 'prefer_not'
  const draft: Mark = limited ? { state, from, to } : { state, from: null, to: null }
  const empty = limited && from === to

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()} title={dayTitle(parseDate(date))}>
      <div className="grid gap-5">
        <StatePicker label="Stan dnia" value={state} onChange={setState} />
        <fieldset className="m-0 grid gap-2 border-0 p-0">
          <legend className="mb-2 font-semibold">Godziny</legend>
          {[false, true].map((option) => (
            <label
              key={String(option)}
              className={cn(
                'flex min-h-(--touch) cursor-pointer items-center gap-3 rounded-md border-2 border-line bg-surface px-3',
                limited === option && 'border-accent bg-accent-soft',
              )}
            >
              <input
                type="radio"
                name="hours-kind"
                className="size-5 accent-accent"
                checked={limited === option}
                onChange={() => setLimited(option)}
              />
              {option ? (restricting ? 'Tylko w tych godzinach' : 'Mogę tylko w tych godzinach') : 'Cały dzień'}
            </label>
          ))}
        </fieldset>
        {limited && (
          <div className="grid gap-3">
            <div className="grid grid-cols-2 gap-3">
              <TimeSelect id="hours-from" label="Od" value={from} onChange={setFrom} asEnd={false} />
              <TimeSelect id="hours-to" label="Do" value={to} onChange={setTo} asEnd />
            </div>
            <p className="m-0 text-sm text-ink-muted">
              {empty
                ? 'Początek i koniec są takie same. Zmień jedną z godzin.'
                : [
                    overnight(draft) ? 'Do rana następnego dnia, na przykład na nockę.' : '',
                    restricting
                      ? 'W pozostałych godzinach tego dnia możesz pracować.'
                      : 'Zmiany, która nie mieści się w tych godzinach, tego dnia nie dostaniesz.',
                  ]
                    .filter(Boolean)
                    .join(' ')}
            </p>
          </div>
        )}
        <Button wide disabled={empty} onClick={() => onSave(draft)}>
          Zapisz ten dzień
        </Button>
      </div>
    </Sheet>
  )
}

function TimeSelect({
  id,
  label,
  value,
  onChange,
  asEnd,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  asEnd: boolean
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="font-semibold">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-(--touch-main) rounded-md border-2 border-ink bg-surface px-3 text-lg tabular-nums"
      >
        {TIMES.map((time) => (
          <option key={time} value={time}>
            {timeLabel(time, asEnd)}
          </option>
        ))}
      </select>
    </div>
  )
}
