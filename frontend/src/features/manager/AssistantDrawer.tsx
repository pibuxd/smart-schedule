import { MessageCircle } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import type { ManagerOverviewOut } from '../../api/generated/model'
import { useManagerOverview } from '../../api/generated/tenancy/tenancy'
import { AssistantFab } from '../../components/assistant/AssistantFab'
import { Button } from '../../components/ui/button'
import { Drawer } from '../../components/ui/drawer'
import { EmptyState, ErrorState, Loading } from '../../components/ui/status'
import { errorMessage } from '../../lib/api-error'
import { AssistantPanel } from './Assistant'
import { AssistantDrawerContext, useAssistantDrawer, type OpenOptions } from './assistant-drawer'
import { useManager } from './ManagerContext'

type Chat = OpenOptions & { visit: number }

/**
 * One assistant chat for the whole manager panel: the "Asystent" button in the bottom right corner opens it on
 * every screen, and it slides in from the right over whatever is open, so the manager can agree a rule and watch
 * it land in the period's agreements without leaving the screen. The chat is about one location: the one on screen,
 * otherwise the last one (or the only one); with several and none chosen yet, the manager picks one first.
 */
export function AssistantDrawerProvider({ children }: { children: ReactNode }) {
  const { readOnly } = useManager()
  const [open, setOpen] = useState(false)
  // The live location on screen, and the last location the chat was about.
  const [onScreen, setOnScreen] = useState<string | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  // A new draft or period remounts the chat (`visit`), so the prefilled text is never stale.
  const [chat, setChat] = useState<Chat>({ visit: 0 })
  const api = useMemo(
    () => ({
      openChat: (options: OpenOptions = {}) => {
        if (options.locationId) setChosen(options.locationId)
        setChat((old) =>
          options.text || options.periodId !== old.periodId || options.locationId !== old.locationId
            ? { ...options, visit: old.visit + 1 }
            : old,
        )
        setOpen(true)
      },
      showLocation: (locationId: string | null) => {
        setOnScreen(locationId)
        if (locationId) setChosen(locationId)
      },
    }),
    [],
  )
  return (
    <AssistantDrawerContext.Provider value={api}>
      {/* On a wide screen the page moves aside, so the agreements stay visible next to the chat. */}
      <div className={open ? 'min-w-0 xl:pr-[420px]' : 'min-w-0'}>{children}</div>
      {!readOnly && !open && <AssistantFab nameFrom="wide" onClick={() => api.openChat()} />}
      <Drawer open={open} onOpenChange={setOpen} title="Asystent" description="Ustal zasadę w rozmowie i zatwierdź ją.">
        <LocationChat onScreen={onScreen} chosen={chosen} onChoose={setChosen} chat={chat} />
      </Drawer>
    </AssistantDrawerContext.Provider>
  )
}

/** The chat of the location on screen; elsewhere of the chosen (or only) location, with a way to pick another. */
function LocationChat({
  onScreen,
  chosen,
  onChoose,
  chat,
}: {
  onScreen: string | null
  chosen: string | null
  onChoose: (locationId: string | null) => void
  chat: Chat
}) {
  const { companyId } = useManager()
  const overview = useManagerOverview({ company_id: companyId }, { query: { enabled: !onScreen } })
  const live = (overview.data?.data as ManagerOverviewOut | undefined)?.locations
  const panel = (locationId: string) => (
    <AssistantPanel
      key={`${locationId}:${chat.visit}`}
      locationId={locationId}
      // A period and a draft belong to the location they were opened for.
      periodId={!chat.locationId || chat.locationId === locationId ? chat.periodId : undefined}
      initialText={!chat.locationId || chat.locationId === locationId ? chat.text : undefined}
    />
  )
  if (onScreen) return panel(onScreen)

  // Until the list arrives, a location opened by name is trusted; then it must still be live.
  const current = live
    ? (live.find((location) => location.id === chosen) ?? (live.length === 1 ? live[0] : undefined))
    : undefined
  const locationId = live ? current?.id : chosen
  if (locationId) {
    return (
      <>
        {live && live.length > 1 && current && (
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-grid py-1 pr-1 pl-4 text-sm">
            <span className="min-w-0 truncate">
              Lokal: <b>{current.name}</b>
            </span>
            <Button variant="quiet" size="normal" className="text-sm" onClick={() => onChoose(null)}>
              Zmień lokal
            </Button>
          </div>
        )}
        {panel(locationId)}
      </>
    )
  }
  if (overview.isError) {
    return (
      <div className="p-4">
        <ErrorState onRetry={() => void overview.refetch()}>
          {errorMessage(overview.error, 'Nie udało się wczytać lokali. Sprawdź internet i spróbuj jeszcze raz.')}
        </ErrorState>
      </div>
    )
  }
  if (!live) return <Loading>Wczytuję lokale…</Loading>
  if (live.length === 0) {
    return (
      <div className="p-4">
        <EmptyState title="Nie masz jeszcze lokalu">Asystent pomaga w grafiku lokalu. Dodaj lokal na ekranie „Lokale”.</EmptyState>
      </div>
    )
  }
  return (
    <div className="grid content-start gap-3 overflow-y-auto p-4">
      <h3 className="m-0 text-lg font-semibold">O którym lokalu rozmawiamy?</h3>
      <ul className="m-0 grid list-none gap-2 p-0">
        {live.map((location) => (
          <li key={location.id}>
            <Button variant="secondary" size="normal" wide className="justify-start text-left" onClick={() => onChoose(location.id)}>
              {location.name}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** A button that slides the chat in for one location and period ("Ustal w rozmowie"); nothing outside the panel. */
export function OpenAssistantButton({
  locationId,
  periodId,
  children = 'Asystent',
  variant = 'secondary',
}: {
  locationId?: string
  periodId?: string
  children?: ReactNode
  variant?: 'primary' | 'secondary'
}) {
  const drawer = useAssistantDrawer()
  if (!drawer) return null
  return (
    <Button variant={variant} size="normal" onClick={() => drawer.openChat({ locationId, periodId })}>
      <MessageCircle aria-hidden="true" size={18} />
      {children}
    </Button>
  )
}
