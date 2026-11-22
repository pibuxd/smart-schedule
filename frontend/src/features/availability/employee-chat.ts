import { createContext, useContext, useEffect } from 'react'

/** One conversation: the period the manager asked for (`periodId`), or before that a month (`month`, its first day). */
export type ChatScope = { periodId?: string; month?: string; editable: boolean }

export type EmployeeChat = {
  open: boolean
  /** The assistant reads the messages (the server has a key); without it they go to the manager as written. */
  assistantReads: boolean
  /** False when the company's access has expired: no "Asystent" button then. */
  available: boolean
  /** Opens the chat on this conversation, or without one on the screen's own, or the nearest open one. */
  openChat: (scope?: ChatScope) => void
  setScreenScope: (scope: ChatScope | null) => void
}

export const EmployeeChatContext = createContext<EmployeeChat | null>(null)

/** The employee's chat (`EmployeeChatProvider` in the employee layout); null outside it. */
export function useEmployeeChat() {
  return useContext(EmployeeChatContext)
}

/** A screen about one month ("Kiedy mogę") makes the "Asystent" button talk about that month while it is open. */
export function useScreenChatScope({ periodId, month, editable }: ChatScope) {
  const set = useEmployeeChat()?.setScreenScope
  useEffect(() => {
    if (!set) return
    set({ periodId, month, editable })
    return () => set(null)
  }, [set, periodId, month, editable])
}
