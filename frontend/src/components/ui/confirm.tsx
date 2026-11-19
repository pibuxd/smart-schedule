import type { ReactNode } from 'react'

import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { Button } from './button'
import { Sheet } from './sheet'
import { InlineError } from './status'

/** Asks once more before something is removed for good: says what happens, then "Tak, …" or "Zostaw". */
export function ConfirmSheet({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  onConfirm,
  pending = false,
  error,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
  confirmLabel: string
  onConfirm: () => void
  pending?: boolean
  error?: unknown
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title={title}>
      <div className="grid gap-4">
        <div className="grid gap-2">{children}</div>
        {error ? <InlineError>{errorMessage(error, NETWORK_PROBLEM)}</InlineError> : null}
        <Button variant="danger" wide disabled={pending} onClick={onConfirm}>
          {confirmLabel}
        </Button>
        <Button variant="secondary" wide onClick={() => onOpenChange(false)}>
          Zostaw
        </Button>
      </div>
    </Sheet>
  )
}
