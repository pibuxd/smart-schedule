import type { InputHTMLAttributes } from 'react'
import { ChevronDown } from 'lucide-react'

import { cn } from '../../lib/cn'
import { OTHER_COUNTRY, PHONE_COUNTRIES, phoneCountry } from './phone'

/**
 * A phone number with its country in front: "+48" unless someone picks another one. The country list is the
 * phone's own (a plain select under the visible code), so it opens the way every other list does; the number is
 * typed after it. A number typed with "+" is taken as it is, whatever country is picked (`phoneToSend`).
 * `variant` "main" is the big field of the login screen, "form" the size of the manager's forms.
 */
export function PhoneInput({
  region,
  onRegionChange,
  variant = 'main',
  className,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & {
  region: string
  onRegionChange: (region: string) => void
  variant?: 'main' | 'form'
}) {
  const country = phoneCountry(region)
  return (
    <div
      className={cn(
        'flex overflow-hidden border-2 bg-surface focus-within:border-accent',
        variant === 'main'
          ? 'min-h-(--touch-main) rounded-md border-ink focus-within:ring-3 focus-within:ring-accent-soft'
          : 'min-h-(--touch) rounded-sm border-line',
        className,
      )}
    >
      <span className="relative flex shrink-0 items-center gap-1 bg-grid px-3 font-semibold">
        <span aria-hidden="true">{country ? `+${country.code}` : 'Inny'}</span>
        <ChevronDown aria-hidden="true" size={16} />
        <select
          aria-label="Kraj numeru"
          className="absolute inset-0 cursor-pointer text-base opacity-0"
          value={region}
          disabled={input.disabled}
          onChange={(event) => {
            onRegionChange(event.target.value)
            // Straight on to the number (on a phone the keyboard opens).
            if (input.id) document.getElementById(input.id)?.focus()
          }}
        >
          {PHONE_COUNTRIES.map((c) => (
            <option key={c.region} value={c.region}>{`${c.name} +${c.code}`}</option>
          ))}
          <option value={OTHER_COUNTRY}>Inny kraj (wpisz numer z +)</option>
        </select>
      </span>
      <input
        type="tel"
        inputMode="tel"
        placeholder={country ? country.example : '+ kierunkowy i numer'}
        className={cn(
          'min-w-0 flex-1 bg-transparent px-3.5 text-ink outline-none disabled:text-ink-muted',
          variant === 'main' ? 'text-lg tracking-wide' : 'text-base',
        )}
        {...input}
      />
    </div>
  )
}
