import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * A panel that slides in from the right edge and stays open while the person works on the page behind it
 * (Radix Dialog, not modal). Full width on a phone. Closes with "Zamknij" or Escape, never by a tap outside.
 */
export function Drawer({
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
    <Dialog.Root open={open} onOpenChange={onOpenChange} modal={false}>
      <Dialog.Portal>
        <Dialog.Content
          onInteractOutside={(event) => event.preventDefault()}
          className="drawer-panel fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-line bg-surface shadow-drawer sm:w-[420px]"
        >
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-grid py-1 pr-1 pl-4">
            <div className="min-w-0">
              <Dialog.Title className="m-0 text-base font-semibold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="m-0 truncate text-xs text-ink-muted">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close className="inline-flex min-h-(--touch) shrink-0 cursor-pointer items-center justify-center gap-1 rounded-md px-3 text-sm font-semibold text-accent hover:bg-accent-soft">
              <X aria-hidden="true" size={20} />
              Zamknij
            </Dialog.Close>
          </div>
          <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
