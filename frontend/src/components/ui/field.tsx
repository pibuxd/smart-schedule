import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { useId } from 'react'

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
  children,
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  const id = useId()
  return (
    <div className={cn('grid content-start gap-1', className)}>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <select id={id} className={inputClass} {...props}>
        {children}
      </select>
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
    <label className={cn('flex min-h-(--touch) cursor-pointer items-start gap-3 py-2', className)}>
      <input type="checkbox" className="mt-0.5 size-6 shrink-0 cursor-pointer accent-accent" {...props} />
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

/** A titled section of a screen: a heading with an optional action on the right. */
export function Section({
  title,
  action,
  children,
  description,
}: {
  title: string
  action?: ReactNode
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1">
          <h2 className="m-0 text-lg font-extrabold">{title}</h2>
          {description && <p className="m-0 text-sm text-ink-muted">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}
