import { createContext, useContext, useEffect } from 'react'

export type OpenOptions = {
  /** The location to talk about; without it, the one on screen or the last one. */
  locationId?: string
  /** The availability period the agreements are for; without it the server picks the newest open one. */
  periodId?: string
  /** Text put into the message field (never sent by itself). */
  text?: string
}

export const AssistantDrawerContext = createContext<{
  openChat: (options?: OpenOptions) => void
  /** The location on screen (null when none, or when it is archived): the chat talks about it. */
  showLocation: (locationId: string | null) => void
} | null>(null)

/** Opens the assistant chat from any manager screen. Null outside the manager panel (the caller hides its button). */
export function useAssistantDrawer() {
  return useContext(AssistantDrawerContext)
}

/** A location's screens tell the chat which location is on screen. */
export function useChatLocation(locationId: string | null) {
  const show = useAssistantDrawer()?.showLocation
  useEffect(() => {
    if (!show) return
    show(locationId)
    return () => show(null)
  }, [show, locationId])
}
