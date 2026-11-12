import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { cn } from '../../lib/cn'
import { WEEKDAY_HEADERS } from '../../lib/dates'
import type { AvailabilityState } from './marks'
import { StatePicker } from './StatePicker'

const WEEKDAY_NAMES = ['poniedziałki', 'wtorki', 'środy', 'czwartki', 'piątki', 'soboty', 'niedziele']

/** "Powtarzaj co tydzień do…" and "Skopiuj z poprzedniego miesiąca". */
export function MoreOptionsSheet({
  open,
  onOpenChange,
  periodEnd,
  busy,
  error,
  onRepeat,
  onCopy,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  periodEnd: string
  busy: boolean
  error: string | null
  onRepeat: (weekdays: number[], state: AvailabilityState, until: string) => void
  onCopy: () => void
}) {
  const [weekdays, setWeekdays] = useState<number[]>([])
  const [state, setState] = useState<AvailabilityState>('cannot')
  const [until, setUntil] = useState(periodEnd)

  const toggle = (day: number) =>
    setWeekdays((days) => (days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort()))

  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Więcej opcji">
      <div className="grid gap-6">
        <section className="grid gap-3" aria-labelledby="repeat-title">
          <h3 id="repeat-title" className="m-0 text-lg font-extrabold">
            Powtarzaj co tydzień
          </h3>
          <p className="m-0 text-sm text-ink-muted">
            Na przykład: we wtorki i czwartki mam zajęcia do końca semestru, więc wtedy nie mogę. Zastąpi to, co jest
            już zaznaczone w te dni; w razie pomyłki użyj „Cofnij”.
          </p>
          <div role="group" aria-label="Dni tygodnia" className="grid grid-cols-7 gap-1">
            {WEEKDAY_HEADERS.map((name, day) => (
              <button
                key={name}
                type="button"
                aria-pressed={weekdays.includes(day)}
                aria-label={WEEKDAY_NAMES[day]}
                onClick={() => toggle(day)}
                className={cn(
                  'min-h-(--touch) cursor-pointer rounded-sm border-2 border-line bg-surface text-sm font-semibold',
                  weekdays.includes(day) && 'border-accent bg-accent text-accent-ink',
                )}
              >
                {name}
              </button>
            ))}
          </div>
          <StatePicker label="Co zaznaczyć w te dni" value={state} onChange={setState} />
          <div className="grid gap-1.5">
            <label htmlFor="repeat-until" className="font-semibold">
              Powtarzaj do dnia
            </label>
            <input
              id="repeat-until"
              type="date"
              value={until}
              min={periodEnd.slice(0, 8) + '01'}
              onChange={(event) => setUntil(event.target.value)}
              className="min-h-(--touch-main) rounded-md border-2 border-ink bg-surface px-3 text-lg"
            />
          </div>
          <Button wide disabled={busy || weekdays.length === 0 || !until} onClick={() => onRepeat(weekdays, state, until)}>
            {weekdays.length === 0
              ? 'Wybierz dni tygodnia'
              : `Zaznacz ${weekdays.map((d) => WEEKDAY_NAMES[d]).join(', ')}`}
          </Button>
        </section>
        <section className="grid gap-3 border-t border-line pt-5" aria-labelledby="copy-title">
          <h3 id="copy-title" className="m-0 text-lg font-extrabold">
            Tak samo jak w poprzednim miesiącu
          </h3>
          <p className="m-0 text-sm text-ink-muted">
            Każdy dzień dostanie to, co było zaznaczone w ten sam dzień tygodnia miesiąc wcześniej. Potem możesz
            poprawić pojedyncze dni albo wszystko cofnąć przyciskiem „Cofnij”.
          </p>
          <Button variant="secondary" wide disabled={busy} onClick={onCopy}>
            Skopiuj z poprzedniego miesiąca
          </Button>
        </section>
        {error && <InlineError>{error}</InlineError>}
      </div>
    </Sheet>
  )
}
