import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { ChevronRight, Info } from 'lucide-react'
import { useId, useState } from 'react'

import { cn } from '../../lib/cn'

// Form building blocks for the manager's screens, styled only with the Grafikomat tokens.

export const inputClass =
  'min-h-(--touch) w-full rounded-sm border-2 border-line bg-surface px-3 text-base text-ink ' +
  'focus:border-accent disabled:bg-paper disabled:text-ink-muted'

/** A labelled input. The label is always visible (no placeholder-only fields). */
export function TextField({
  label,
  hint,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode }) {
  const id = useId()
  return (
    <div className={cn('grid content-start gap-1', className)}>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <input id={id} className={inputClass} {...props} />
      {hint && <p className="m-0 text-sm text-ink-muted">{hint}</p>}
    </div>
  )
}

export function SelectField({
  label,
  hint,
  children,
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: ReactNode; children: ReactNode }) {
  const id = useId()
  const hintId = useId()
  return (
    <div className={cn('grid content-start gap-1', className)}>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <select id={id} className={inputClass} aria-describedby={hint ? hintId : undefined} {...props}>
        {children}
      </select>
      {hint && (
        <p id={hintId} className="m-0 text-sm text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  )
}

/** A big tick box with its label as part of the touch area. */
export function CheckField({
  label,
  hint,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode }) {
  return (
    <label className={cn('flex min-h-(--touch) cursor-pointer items-start gap-2.5 py-1.5', className)}>
      <input type="checkbox" className="mt-0.5 size-5 shrink-0 cursor-pointer accent-accent" {...props} />
      <span className="grid gap-0.5">
        <span className="font-semibold">{label}</span>
        {hint && <span className="text-sm text-ink-muted">{hint}</span>}
      </span>
    </label>
  )
}

/** Small label next to a name: "z grupy", "po terminie"… Never colour alone: it always has words. */
export function Tag({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'accent' | 'warn' | 'bad' }) {
  const tones = {
    muted: 'border-line bg-paper text-ink-muted',
    accent: 'border-accent bg-accent-soft text-accent',
    warn: 'border-prefer-not bg-prefer-not-soft text-prefer-not',
    bad: 'border-cannot bg-cannot-soft text-cannot',
  }
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-sm font-semibold', tones[tone])}>
      {children}
    </span>
  )
}

/**
 * A titled section of a screen: a heading with an optional action on the right.
 * The description stays hidden until the "i" button next to the heading is pressed, so screens are not walls of text.
 * `collapsible` folds the whole section under its heading (closed at first), for things the manager rarely needs.
 */
export function Section({
  title,
  action,
  children,
  description,
  collapsible = false,
}: {
  title: string
  action?: ReactNode
  description?: ReactNode
  collapsible?: boolean
  children: ReactNode
}) {
  const [explained, setExplained] = useState(false)
  const descriptionId = useId()
  if (collapsible) {
    return (
      <details className="group rounded-md border border-line bg-surface">
        <summary className="flex min-h-(--touch) cursor-pointer list-none items-center gap-2 px-3 [&::-webkit-details-marker]:hidden">
          <ChevronRight aria-hidden="true" size={18} className="shrink-0 text-accent group-open:rotate-90" />
          <h2 className="m-0 text-base font-extrabold">{title}</h2>
        </summary>
        <div className="grid gap-2 px-3 pb-3">
          {description && <p className="m-0 text-sm text-ink-muted">{description}</p>}
          {children}
        </div>
      </details>
    )
  }
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1">
          <div className="flex items-center gap-1">
            <h2 className="m-0 text-lg font-extrabold">{title}</h2>
            {description && (
              <button
                type="button"
                aria-label={`Wyjaśnij: ${title}`}
                aria-expanded={explained}
                aria-controls={descriptionId}
                onClick={() => setExplained((open) => !open)}
                className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-full text-accent hover:bg-accent-soft"
              >
                <Info aria-hidden="true" size={18} />
              </button>
            )}
          </div>
          {description && explained && (
            <p id={descriptionId} className="m-0 max-w-[70ch] text-sm text-ink-muted">
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}
