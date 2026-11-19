import { createContext, useContext } from 'react'

export type OpenOptions = {
  /** The availability period the agreements are for; without it the server picks the newest open one. */
  periodId?: string
  /** Text put into the message field (never sent by itself). */
  text?: string
}

export const AssistantDrawerContext = createContext<{
  openChat: (options?: OpenOptions) => void
} | null>(null)

/** Opens the assistant chat from any screen of a location. Null outside a location (the caller hides its button). */
export function useAssistantDrawer() {
  return useContext(AssistantDrawerContext)
}
