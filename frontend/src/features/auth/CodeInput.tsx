import { useRef } from 'react'

import { cn } from '../../lib/cn'

/**
 * Six big boxes for the SMS code. Underneath is one ordinary input, so the phone can fill the code
 * from the SMS (autocomplete="one-time-code") and pasting works.
 */
export function CodeInput({
  value,
  onChange,
  disabled,
  invalid,
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  invalid?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const digits = value.padEnd(6, ' ').slice(0, 6).split('')
  const active = Math.min(value.length, 5)

  return (
    <div className="relative" onClick={() => input.current?.focus()}>
      <div className="grid grid-cols-6 gap-2" aria-hidden="true">
        {digits.map((digit, i) => (
          <span
            key={i}
            className={cn(
              'grid h-16 place-items-center rounded-md border-2 bg-surface text-xl font-extrabold tabular-nums',
              invalid ? 'border-cannot' : 'border-line',
              !disabled && i === active && 'border-accent ring-3 ring-accent-soft',
            )}
          >
            {digit.trim()}
          </span>
        ))}
      </div>
      <input
        ref={input}
        id="login-code"
        aria-label="Kod z SMS-a, 6 cyfr"
        aria-invalid={invalid || undefined}
        className="absolute inset-0 h-full w-full cursor-text opacity-0"
        inputMode="numeric"
        autoComplete="one-time-code"
        autoFocus
        maxLength={6}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, '').slice(0, 6))}
      />
    </div>
  )
}
