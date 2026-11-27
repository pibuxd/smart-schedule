import type { ReactNode } from 'react'

import { cn } from '../../lib/cn'

/**
 * An on/off switch (`role="switch"`) with its label as part of the touch area. Never colour alone: the knob moves
 * to the right and fills in when on.
 */
export function Switch({
  label,
  checked,
  onCheckedChange,
  disabled,
  className,
}: {
  label: ReactNode
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
}) {
  return (
    <label
      className={cn(
        'flex min-h-(--touch) items-center justify-between gap-3',
        disabled ? 'cursor-not-allowed' : 'cursor-pointer',
        className,
      )}
    >
      <span className="font-semibold">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          'relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border-2 transition-colors',
          'disabled:cursor-not-allowed disabled:opacity-60',
          checked ? 'border-accent bg-accent' : 'border-ink-muted bg-surface',
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'size-5 rounded-full transition-transform',
            checked ? 'translate-x-5.5 bg-surface' : 'translate-x-0.5 bg-ink-muted',
          )}
        />
      </button>
    </label>
  )
}
