import type { ReactNode } from 'react'

import { Button } from './button'

/** Loading state: plain words, no spinner-only screens. */
export function Loading({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="py-10 text-center text-lg text-ink-muted">
      {children}
    </p>
  )
}

/** Error state: what went wrong in plain words, and a way to try again. */
export function ErrorState({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <div role="alert" className="grid gap-4 rounded-lg border border-cannot bg-cannot-soft p-5">
      <p className="m-0 text-cannot">{children}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Spróbuj jeszcze raz
        </Button>
      )}
    </div>
  )
}

/** Empty state: says what will appear here and what to do now. */
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-3 rounded-lg border-2 border-dashed border-line bg-surface p-6">
      <h2 className="m-0 text-lg font-extrabold">{title}</h2>
      <div className="grid gap-4 text-ink-muted">{children}</div>
    </div>
  )
}

/** Short inline message under a form field or action. */
export function InlineError({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="m-0 rounded-sm bg-cannot-soft px-3 py-2 text-sm text-cannot">
      {children}
    </p>
  )
}
