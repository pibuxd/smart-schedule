import { MessageCircle } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import { Button } from '../../components/ui/button'
import { Drawer } from '../../components/ui/drawer'
import { AssistantPanel } from './Assistant'
import { AssistantDrawerContext, useAssistantDrawer, type OpenOptions } from './assistant-drawer'

/**
 * One assistant chat per location: it slides in from the right over whichever tab is open, so the manager can
 * agree a rule and watch it land in the period's agreements without leaving the screen.
 */
export function AssistantDrawerProvider({ locationId, children }: { locationId: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  // A new draft or period remounts the chat (`visit`), so the prefilled text is never stale.
  const [chat, setChat] = useState<OpenOptions & { visit: number }>({
    visit: 0,
  })
  const api = useMemo(
    () => ({
      openChat: (options: OpenOptions = {}) => {
        setChat((old) =>
          options.text || options.periodId !== old.periodId ? { ...options, visit: old.visit + 1 } : old,
        )
        setOpen(true)
      },
    }),
    [],
  )
  return (
    <AssistantDrawerContext.Provider value={api}>
      {/* On a wide screen the page moves aside, so the agreements stay visible next to the chat. */}
      <div className={open ? 'min-w-0 xl:pr-[420px]' : 'min-w-0'}>{children}</div>
      <Drawer open={open} onOpenChange={setOpen} title="Asystent" description="Ustal zasadę w rozmowie i zatwierdź ją.">
        <AssistantPanel
          key={`${locationId}:${chat.visit}`}
          locationId={locationId}
          periodId={chat.periodId}
          initialText={chat.text}
        />
      </Drawer>
    </AssistantDrawerContext.Provider>
  )
}

/** The button that slides the chat in; renders nothing outside a location. */
export function OpenAssistantButton({
  periodId,
  children = 'Asystent',
  variant = 'secondary',
}: {
  periodId?: string
  children?: ReactNode
  variant?: 'primary' | 'secondary'
}) {
  const drawer = useAssistantDrawer()
  if (!drawer) return null
  return (
    <Button variant={variant} size="normal" onClick={() => drawer.openChat({ periodId })}>
      <MessageCircle aria-hidden="true" size={18} />
      {children}
    </Button>
  )
}
