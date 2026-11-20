import { ChevronRight } from 'lucide-react'
import type { DetailsHTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/cn'

/**
 * Something that folds open under a clickable line. Every fold in the app uses this, so they all look alike:
 * a chevron that turns down when open and a tint under the pointer.
 * `boxed` draws a bordered box around the whole fold (a section of a screen); plain folds sit in the flow of text,
 * and their tint reaches a little past the text on both sides.
 * The chevron and the rounded corners follow only their own `<details>`, so folds can sit inside each other.
 */
export function Disclosure({
  summary,
  children,
  boxed = false,
  className,
  summaryClassName,
  contentClassName,
  ...props
}: DetailsHTMLAttributes<HTMLDetailsElement> & {
  summary: ReactNode
  boxed?: boolean
  summaryClassName?: string
  /** Only for `boxed`: classes of the padded box under the summary. */
  contentClassName?: string
  children: ReactNode
}) {
  return (
    <details className={cn(boxed && 'rounded-md border border-line bg-surface', className)} {...props}>
      <summary
        className={cn(
          'flex min-h-(--touch) cursor-pointer list-none items-center gap-2 transition-colors hover:bg-accent-soft',
          '[&::-webkit-details-marker]:hidden',
          boxed ? 'rounded-md px-3 [details[open]>&]:rounded-b-none' : '-mx-2 rounded-sm px-2',
          summaryClassName,
        )}
      >
        <ChevronRight
          aria-hidden="true"
          className="size-[1.2em] shrink-0 text-accent transition-transform [details[open]>summary>&]:rotate-90"
        />
        {summary}
      </summary>
      {boxed ? <div className={cn('px-3 pb-3', contentClassName)}>{children}</div> : children}
    </details>
  )
}
