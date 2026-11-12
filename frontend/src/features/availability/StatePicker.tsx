import { cn } from '../../lib/cn'
import { type AvailabilityState, STATE_LABEL, STATES } from './marks'
import { StateIcon } from './StateIcon'

/** Four big buttons, one per state; the chosen one is outlined in the accent colour. */
export function StatePicker({
  value,
  onChange,
  label,
  extra,
}: {
  value: AvailabilityState | null
  onChange: (state: AvailabilityState) => void
  label: string
  extra?: React.ReactNode
}) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-2 gap-2">
      {STATES.map((state) => (
        <button
          key={state}
          type="button"
          aria-pressed={value === state}
          onClick={() => onChange(state)}
          className={cn(
            'flex min-h-(--touch-main) cursor-pointer items-center gap-2.5 rounded-md border-2 border-line bg-surface px-3 text-left font-semibold',
            value === state && 'border-accent bg-accent-soft ring-3 ring-accent-soft',
          )}
        >
          <i className={cn(`avail-${state}`, 'grid size-7.5 flex-none place-items-center rounded-sm border-2')}>
            <StateIcon state={state} size={18} />
          </i>
          {STATE_LABEL[state]}
        </button>
      ))}
      {extra}
    </div>
  )
}
