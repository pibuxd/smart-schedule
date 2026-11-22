import { useQueryClient } from '@tanstack/react-query'
import { MessageCircle } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import { getMyAvailabilityQueryKey, useMyAvailability } from '../../api/generated/availability/availability'
import type { MyAvailabilityOut } from '../../api/generated/model'
import { AssistantFab } from '../../components/assistant/AssistantFab'
import { Drawer } from '../../components/ui/drawer'
import { ErrorState, Loading } from '../../components/ui/status'
import { cn } from '../../lib/cn'
import { toIsoDate } from '../../lib/dates'
import { EmployeeChatContext, useEmployeeChat, type ChatScope } from './employee-chat'
import { RequestsChat } from './RequestsSection'

/** The first day of this month: the conversation before the manager asks for a period. */
const thisMonth = (today: Date) => toIsoDate(new Date(today.getFullYear(), today.getMonth(), 1))

/**
 * The employee's chat, one for every screen: the "Asystent" button opens it (a tab on a phone, the corner button
 * on a computer), and so does "Twoje prośby". It talks about the month on "Kiedy mogę" while that screen is open;
 * elsewhere about the period the manager asked for, or this month before that.
 */
export function EmployeeChatProvider({
  companyId,
  readOnly,
  children,
}: {
  companyId: string
  readOnly: boolean
  children: ReactNode
}) {
  const queryClient = useQueryClient()
  const params = { company_id: companyId }
  // A key of its own: "Kiedy mogę" always starts from the server, and this copy must not keep its query alive.
  const queryKey = [...getMyAvailabilityQueryKey(params), 'chat']
  const availability = useMyAvailability(params, { query: { queryKey } })
  const [open, setOpen] = useState(false)
  const [asked, setAsked] = useState<ChatScope | null>(null)
  const [screen, setScreen] = useState<ChatScope | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const actions = useMemo(
    () => ({
      openChat: (scope?: ChatScope) => {
        setAsked(scope ?? null)
        setOpen(true)
        // The manager may have asked for a period since the app was opened.
        void queryClient.invalidateQueries({ queryKey: [...getMyAvailabilityQueryKey({ company_id: companyId }), 'chat'] })
      },
      setScreenScope: (scope: ChatScope | null) => {
        setScreen(scope)
        setAsked(null)
      },
    }),
    [queryClient, companyId],
  )
  const data = availability.data?.data as MyAvailabilityOut | undefined
  // Until the server answers, the button says "Asystent" (the usual case).
  const assistantReads = data ? (data.assistant_reads ?? false) : true
  const value = useMemo(
    () => ({ ...actions, open, assistantReads, available: !readOnly }),
    [actions, open, assistantReads, readOnly],
  )
  const nearest: ChatScope | null = data
    ? data.period?.editable
      ? { periodId: data.period.id, editable: true }
      : { month: thisMonth(new Date()), editable: true }
    : null
  const scope = data ? (asked ?? (screen?.editable ? screen : null) ?? nearest) : null
  const key = scope ? `${scope.periodId ?? scope.month}:${scope.editable}` : ''

  return (
    <EmployeeChatContext.Provider value={value}>
      {children}
      {!readOnly && !open && (
        // On a phone the button is a tab in the bar at the bottom (`EmployeeChatTab`).
        <AssistantFab label={chatLabel(assistantReads)} className="hidden md:inline-flex" onClick={() => actions.openChat()} />
      )}
      <Drawer
        open={open}
        onOpenChange={setOpen}
        title={assistantReads ? 'Asystent' : 'Prośby do kierownika'}
        description={assistantReads ? 'Zapytaj o swój grafik albo napisz prośbę.' : 'Napisz prośbę do kierownika.'}
      >
        {scope ? (
          <RequestsChat
            key={key}
            companyId={companyId}
            periodId={scope.periodId}
            month={scope.month}
            editable={scope.editable}
            assistantReads={assistantReads}
            text={drafts[key] ?? ''}
            onTextChange={(text) => setDrafts((old) => ({ ...old, [key]: text }))}
          />
        ) : availability.isError ? (
          <div className="p-4">
            <ErrorState onRetry={() => void availability.refetch()}>
              Nie udało się otworzyć rozmowy. Sprawdź internet i spróbuj jeszcze raz.
            </ErrorState>
          </div>
        ) : (
          <Loading>Otwieram rozmowę…</Loading>
        )}
      </Drawer>
    </EmployeeChatContext.Provider>
  )
}

const chatLabel = (assistantReads: boolean) => (assistantReads ? 'Asystent' : 'Prośby')

/** The chat as the last tab of the bar at the bottom of a phone; on a computer the corner button opens it. */
export function EmployeeChatTab({ className }: { className?: string }) {
  const chat = useEmployeeChat()
  if (!chat?.available) return null
  return (
    <button
      type="button"
      onClick={() => chat.openChat()}
      className={cn(
        'grid min-h-16 min-w-0 cursor-pointer place-items-center gap-0.5 px-0.5 py-2 text-sm font-semibold whitespace-nowrap text-ink-muted',
        className,
      )}
    >
      <MessageCircle aria-hidden="true" size={26} />
      {chatLabel(chat.assistantReads)}
    </button>
  )
}
