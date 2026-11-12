import { useEffect, useRef } from 'react'

import { cn } from '../../lib/cn'
import { dayTitle, parseDate, WEEKDAY_HEADERS } from '../../lib/dates'
import { calendarWeeks } from './calendar-weeks'
import { cellHours, describeMark, type Mark, markOf, type Marks } from './marks'
import { StateIcon } from './StateIcon'

/**
 * The period as a squared-paper grid. Press on a day and drag across others to mark them all
 * (`onStroke` gets every day touched in one movement, once, when the finger lifts).
 * Keyboard: Tab to a day and press Enter or Space.
 */
export function AvailabilityCalendar({
  start,
  end,
  marks,
  disabled,
  onPaint,
  onStroke,
  onOpenDay,
}: {
  start: string
  end: string
  marks: Marks
  disabled: boolean
  /** Called for each day as the finger passes, so it changes colour at once. */
  onPaint: (date: string) => void
  onStroke: () => void
  /** When set, a tap opens the day instead of painting (the "Godziny dnia" tool). */
  onOpenDay?: (date: string) => void
}) {
  const painting = useRef(false)

  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!painting.current) return
      const element = document.elementFromPoint?.(event.clientX, event.clientY)
      const date = element?.closest<HTMLElement>('[data-date]')?.dataset.date
      if (date) onPaint(date)
    }
    const up = () => {
      if (!painting.current) return
      painting.current = false
      onStroke()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [onPaint, onStroke])

  return (
    <div
      role="grid"
      aria-label="Kalendarz dni"
      className="grid touch-none grid-cols-7 gap-1 select-none"
    >
      <div role="row" className="contents">
        {WEEKDAY_HEADERS.map((name, i) => (
          <div
            key={name}
            role="columnheader"
            className={cn('pb-0.5 text-center text-xs font-semibold', i > 4 ? 'text-ink' : 'text-ink-muted')}
          >
            {name}
          </div>
        ))}
      </div>
      {calendarWeeks(start, end).map((week) => (
        <div role="row" key={week.find(Boolean) ?? ''} className="contents">
          {week.map((date, i) =>
            date ? (
              <DayCell
                key={date}
                date={date}
                mark={markOf(marks, date)}
                disabled={disabled}
                onPointerDown={(event) => {
                  if (disabled || onOpenDay) return
                  event.preventDefault()
                  painting.current = true
                  onPaint(date)
                }}
                onClick={(event) => {
                  if (disabled) return
                  if (onOpenDay) onOpenDay(date)
                  else if (event.detail === 0) {
                    // Keyboard (Enter/Space) or a screen reader: paint this one day.
                    onPaint(date)
                    onStroke()
                  }
                }}
              />
            ) : (
              <div role="gridcell" key={`empty-${i}`} aria-hidden="true" />
            ),
          )}
        </div>
      ))}
    </div>
  )
}

function DayCell({
  date,
  mark,
  disabled,
  onPointerDown,
  onClick,
}: {
  date: string
  mark: Mark
  disabled: boolean
  onPointerDown: (event: React.PointerEvent) => void
  onClick: (event: React.MouseEvent) => void
}) {
  const day = parseDate(date)
  const hours = cellHours(mark)
  return (
    <div role="gridcell" className="min-w-0">
      <button
        type="button"
        data-date={date}
        data-state={mark.state}
        aria-label={`${dayTitle(day)}: ${describeMark(mark)}`}
        aria-disabled={disabled || undefined}
        className={cn(
          `avail-${mark.state}`,
          'grid h-16 w-full min-w-0 cursor-pointer grid-rows-[auto_1fr_auto] justify-items-center rounded-sm border-2 px-0 py-1',
          'transition-colors duration-75',
          disabled && 'cursor-default opacity-75',
        )}
        onPointerDown={onPointerDown}
        onClick={onClick}
      >
        <span className="text-base leading-tight font-extrabold text-ink tabular-nums">{day.getDate()}</span>
        <span className={cn('self-center', mark.state === 'neutral' && 'text-line')}>
          <StateIcon state={mark.state} size={hours ? 16 : 20} />
        </span>
        {hours && <span className="text-cell font-semibold tabular-nums">{hours}</span>}
      </button>
    </div>
  )
}
