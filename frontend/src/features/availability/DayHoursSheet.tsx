import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { cn } from '../../lib/cn'
import { dayTitle, parseDate, shortTime, spanHours } from '../../lib/dates'
import { type AvailabilityState, type Mark, overnight } from './marks'
import { StatePicker } from './StatePicker'

// Every half hour; "00:00" as an end means midnight.
const TIMES = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`)

/** The half hours, plus a saved time between them ("09:15" from "nie mogę 9:15–11:45"), so the list shows it. */
function timesWith(value: string) {
  return TIMES.includes(value) ? TIMES : [...TIMES, value].sort()
}

function timeLabel(value: string, asEnd: boolean) {
  return asEnd && value === '00:00' ? '0:00 (północ)' : shortTime(value)
}

/**
 * One day in detail: the state and, if needed, the hours. "Chętnie"/"Mogę" with hours = "I can only then";
 * "Nie mogę" is always the whole day (Piotr, 25.11.2026), so hours someone cannot work are marked as the hours they can.
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
  const [second, setSecond] = useState(Boolean(mark.from2 && mark.to2))
  const [from2, setFrom2] = useState(mark.from2 ?? '18:00')
  const [to2, setTo2] = useState(mark.to2 ?? '22:00')
  const [oneShift, setOneShift] = useState(Boolean(mark.oneShift))
  const wholeDay = state === 'cannot'
  const hours = limited && !wholeDay
  const two = hours && second
  const draft: Mark = hours
    ? {
        state,
        from,
        to,
        from2: two ? from2 : null,
        to2: two ? to2 : null,
        oneShift: two && oneShift,
      }
    : { state, from: null, to: null }
  const empty = hours && (from === to || (two && from2 === to2))
  // "Od 20:00 do 16:00" is more likely swapped fields than a 20-hour night, so it needs a second look.
  const longNight = hours && !empty && overnight(draft) && spanHours(from, to) > 12

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()} title={dayTitle(parseDate(date))}>
      <div className="grid gap-5">
        <StatePicker label="Stan dnia" value={state} onChange={setState} />
        {wholeDay ? (
          <p className="m-0 text-sm text-ink-muted">
            „Nie mogę” jest na cały dzień. Możesz w części dnia? Wybierz „Mogę” i godziny, w których możesz.
          </p>
        ) : (
          <fieldset className="m-0 grid gap-2 border-0 p-0">
            <legend className="mb-2 font-semibold">Godziny</legend>
            {[false, true].map((option) => (
              <label
                key={String(option)}
                className={cn(
                  'flex min-h-(--touch) cursor-pointer items-center gap-3 rounded-md border-2 border-line bg-surface px-3 py-2',
                  limited === option && 'border-accent bg-accent-soft',
                )}
              >
                <input
                  type="radio"
                  name="hours-kind"
                  className="size-5 flex-none accent-accent"
                  checked={limited === option}
                  onChange={() => setLimited(option)}
                />
                <span>
                  {option ? 'Mogę tylko w tych godzinach' : 'Cały dzień'}
                  {option && (
                    <span className="block text-sm text-ink-muted">
                      Poza tymi godzinami tego dnia nie dostaniesz zmiany.
                    </span>
                  )}
                </span>
              </label>
            ))}
          </fieldset>
        )}
        {hours && (
          <div className="grid gap-3">
            <div className="grid grid-cols-2 gap-3">
              <TimeSelect id="hours-from" label="Od" value={from} onChange={setFrom} asEnd={false} />
              <TimeSelect id="hours-to" label="Do" value={to} onChange={setTo} asEnd />
            </div>
            {longNight ? (
              <div role="alert" className="grid gap-2 rounded-md border-2 border-cannot bg-cannot-soft px-3 py-2">
                <p className="m-0 font-semibold text-cannot">
                  To {spanHours(from, to)} godzin: od {shortTime(from)} do {shortTime(to)} następnego dnia. Może godziny
                  są zamienione?
                </p>
                <Button
                  variant="secondary"
                  size="normal"
                  onClick={() => {
                    setFrom(to)
                    setTo(from)
                  }}
                >
                  Zamień: od {shortTime(to)} do {shortTime(from)}
                </Button>
              </div>
            ) : (
              (empty || overnight(draft)) && (
                <p className={cn('m-0 text-sm', empty ? 'text-cannot' : 'text-ink-muted')}>
                  {empty
                    ? 'Początek i koniec są takie same. Zmień jedną z godzin.'
                    : `Do ${shortTime(to)} następnego dnia, na przykład na nockę.`}
                </p>
              )
            )}
            {two ? (
              <div className="grid gap-3 rounded-md border border-line bg-surface p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">Drugi przedział</span>
                  <Button variant="quiet" size="normal" onClick={() => setSecond(false)}>
                    Usuń
                  </Button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <TimeSelect id="hours-from-2" label="Od" value={from2} onChange={setFrom2} asEnd={false} />
                  <TimeSelect id="hours-to-2" label="Do" value={to2} onChange={setTo2} asEnd />
                </div>
                <fieldset className="m-0 grid gap-2 border-0 p-0">
                  <legend className="mb-1 font-semibold">Ile zmian tego dnia?</legend>
                  {[false, true].map((option) => (
                    <label
                      key={String(option)}
                      className={cn(
                        'flex min-h-(--touch) cursor-pointer items-center gap-3 rounded-md border-2 border-line bg-surface px-3 py-2',
                        oneShift === option && 'border-accent bg-accent-soft',
                      )}
                    >
                      <input
                        type="radio"
                        name="one-shift"
                        className="size-5 flex-none accent-accent"
                        checked={oneShift === option}
                        onChange={() => setOneShift(option)}
                      />
                      <span>
                        {option ? 'Albo: tylko jedna zmiana' : 'Lub: mogę w obu'}
                        <span className="block text-sm text-ink-muted">
                          {option
                            ? 'Dostaniesz najwyżej jedną zmianę, w jednym z tych przedziałów.'
                            : 'Możesz dostać zmianę w każdym z przedziałów.'}
                        </span>
                      </span>
                    </label>
                  ))}
                </fieldset>
              </div>
            ) : (
              <Button variant="secondary" size="normal" className="w-fit" onClick={() => setSecond(true)}>
                Dodaj drugi przedział
              </Button>
            )}
            {!empty && (
              <p className="m-0 rounded-md border border-line bg-paper px-3 py-2">
                Zmiany spoza godzin {shortTime(from)}–{to === '00:00' ? '24:00' : shortTime(to)}
                {two && ` i ${shortTime(from2)}–${to2 === '00:00' ? '24:00' : shortTime(to2)}`} tego dnia nie dostaniesz.
              </p>
            )}
          </div>
        )}
        <Button wide disabled={empty} onClick={() => onSave(draft)}>
          {longNight ? `Tak, do ${shortTime(to)} następnego dnia. Zapisz` : 'Zapisz ten dzień'}
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
    <div className="grid min-w-0 gap-1.5">
      <label htmlFor={id} className="font-semibold">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-(--touch-main) w-full min-w-0 rounded-md border-2 border-ink bg-surface px-3 text-lg tabular-nums"
      >
        {timesWith(value).map((time) => (
          <option key={time} value={time}>
            {timeLabel(time, asEnd)}
          </option>
        ))}
      </select>
    </div>
  )
}
