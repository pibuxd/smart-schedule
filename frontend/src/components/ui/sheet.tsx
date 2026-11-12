import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * A panel that slides up from the bottom on a phone and sits in the middle on a computer
 * (shadcn/ui "sheet" built on Radix Dialog). Always has a visible "Zamknij" button: no hidden gestures.
 */
export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content
          className={
            'fixed inset-x-0 bottom-0 z-50 max-h-[92dvh] overflow-y-auto rounded-t-lg bg-paper px-4 pt-4 ' +
            'pb-[max(24px,env(safe-area-inset-bottom))] shadow-sheet ' +
            'md:inset-auto md:top-1/2 md:left-1/2 md:w-[min(520px,calc(100vw-32px))] md:-translate-x-1/2 ' +
            'md:-translate-y-1/2 md:rounded-lg md:pb-6'
          }
        >
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className="grid gap-1">
              <Dialog.Title className="text-xl font-extrabold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="text-sm text-ink-muted">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close
              className="inline-flex min-h-(--touch) min-w-(--touch) cursor-pointer items-center justify-center gap-1 rounded-md text-sm font-semibold text-accent hover:bg-accent-soft"
            >
              <X aria-hidden="true" size={22} />
              Zamknij
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
