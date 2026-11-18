import { useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import {
  getMyRequestsQueryKey,
  useCreateMyRequest,
  useDeleteMyRequest,
  useMyRequests,
  useUpdateMyRequest,
} from '../../api/generated/availability/availability'
import type { MyRequestOut } from '../../api/generated/model'
import { AssistantMark, ChatComposer, ChatMessage, ChatTyping } from '../../components/assistant/Chat'
import { Button } from '../../components/ui/button'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'

// How long a fresh request is shown as "being read" before we stop asking the server.
const READING_MS = 60_000

/** How the request was understood, in plain words, with a way to say "that is not what I meant". */
function RequestStatus({
  request,
  editable,
  busy,
  onWrong,
}: {
  request: MyRequestOut
  editable: boolean
  busy: boolean
  onWrong: () => void
}) {
  if (request.status === 'superseded') {
    return (
      <p className="m-0 text-sm text-ink-muted">
        Ta prośba została zastąpiona nowszą. Nie wpływa już na układanie grafiku.
      </p>
    )
  }
  if (request.status === 'answered' && request.summary) {
    return (
      <div className="grid gap-2">
        <p className="m-0">{request.summary}</p>
        <p className="m-0 text-sm">
          To odpowiedź asystenta. Przekaż wiadomość, aby dodać ją do listy próśb kierownika.
        </p>
        {editable && (
          <div>
            <Button variant="quiet" size="normal" disabled={busy} onClick={onWrong}>
              Przekaż kierownikowi
            </Button>
          </div>
        )}
      </div>
    )
  }
  if (request.status === 'interpreted' && request.summary) {
    return (
      <div className="grid gap-2">
        <p className="m-0">
          <span className="font-semibold">Tak to zrozumieliśmy: </span>
          {request.summary}
        </p>
        <p className="m-0 text-sm">
          To preferencja, którą generator spróbuje spełnić. Nie zmienia kalendarza dyspozycji. Jeśli nie
          możesz pracować, zaznacz „nie mogę” w kalendarzu.
        </p>
        {editable && (
          <div>
            <Button variant="quiet" size="normal" disabled={busy} onClick={onWrong}>
              Nie o to mi chodziło
            </Button>
          </div>
        )}
      </div>
    )
  }
  if (request.status === 'new') return <ChatTyping>Czytamy Twoją prośbę…</ChatTyping>
  return <p className="m-0 text-sm text-ink-muted">Kierownik przeczyta tę prośbę sam.</p>
}

/**
 * "Coś jeszcze?": a request in words, only for what the calendar cannot say. The manager reads it; when the
 * assistant is on (`assistantReads`), the text also goes to an outside AI service, and the screen says so.
 * It belongs to the period the manager asked for (`periodId`), or, before that, to the month on the screen
 * (`month`, its first day): the manager sees it in every period that covers that month.
 */
function RequestsChat({
  companyId,
  periodId,
  month,
  editable,
  assistantReads = false,
}: {
  companyId: string
  periodId?: string
  month?: string
  editable: boolean
  assistantReads?: boolean
}) {
  const params = periodId ? { company_id: companyId, period_id: periodId } : { company_id: companyId, month }
  const requests = useMyRequests(params, {
    query: {
      // A fresh request is read by the assistant within seconds; look again until it is.
      refetchInterval: (query) => {
        const rows = (query.state.data?.data as MyRequestOut[] | undefined) ?? []
        return rows.some((r) => r.status === 'new' && Date.now() - Date.parse(r.created_at) < READING_MS)
          ? 2000
          : false
      },
    },
  })
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: getMyRequestsQueryKey(params) })
  const create = useCreateMyRequest({ mutation: { onSuccess: refresh } })
  const remove = useDeleteMyRequest({ mutation: { onSuccess: refresh } })
  const [removing, setRemoving] = useState<string | null>(null)
  const update = useUpdateMyRequest({ mutation: { onSuccess: refresh } })
  const [text, setText] = useState('')
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const list = (requests.data?.data as MyRequestOut[] | undefined) ?? []

  const feedRef = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const changeKey = list.map((r) => `${r.id}:${r.status}`).join(',')
  useEffect(() => {
    const feed = feedRef.current
    if (feed && follow.current) feed.scrollTop = feed.scrollHeight
  }, [changeKey])

  return (
    <section
      aria-labelledby="requests-title"
      className="overflow-hidden rounded-lg border border-line bg-surface shadow-chat"
    >
      <header className="flex items-center gap-3 border-b border-grid p-4">
        <AssistantMark />
        <div>
          <h2 id="requests-title" className="m-0 text-lg font-semibold">
            Twoje wiadomości
          </h2>
          <p className="m-0 text-xs text-ink-muted">
            {assistantReads
              ? 'Zapytaj o grafik lub opisz swoją prośbę.'
              : 'Porozmawiaj z kierownikiem o swoim grafiku.'}
          </p>
        </div>
      </header>
      <details className="border-b border-grid px-4 text-sm text-ink-muted">
        <summary className="flex min-h-(--touch) cursor-pointer items-center">
          O wiadomościach i Twoich danych
        </summary>
        <p className="mt-0 mb-4 leading-relaxed">
          Jedna prośba, jedna sprawa. Napisz też powód, jeśli jest ważny. Dyspozycje zaznacz w kalendarzu.{' '}
          {!periodId &&
            'Prośba dotyczy tego miesiąca. Kierownik weźmie ją pod uwagę, gdy będzie układać na niego grafik. '}
          {assistantReads
            ? 'Asystent AI (zewnętrzna usługa Claude) czyta tę wiadomość, Twoje wcześniejsze prośby, dyspozycje i opublikowany grafik ze współpracownikami na Twoich zmianach. Możesz poprawić wcześniejszą prośbę. Prośby czyta też kierownik. Asystent nie układa grafiku ani nie zmienia kalendarza. Nie wpisuj tu nic, czego nie chcesz mu przekazać.'
            : 'Przeczyta to tylko kierownik.'}
        </p>
      </details>
      <div
        ref={feedRef}
        onScroll={() => {
          const f = feedRef.current
          if (f) follow.current = f.scrollHeight - f.scrollTop - f.clientHeight < 100
        }}
        className="max-h-[560px] overflow-y-auto overscroll-contain p-4"
        role="log"
        aria-label="Twoje wiadomości o grafiku"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {requests.isPending && (
          <p role="status" className="m-0 text-sm text-ink-muted">
            Wczytuję wiadomości…
          </p>
        )}
        {requests.isError && (
          <InlineError>
            Nie udało się wczytać Twoich próśb.{' '}
            <button
              className="min-h-(--touch) cursor-pointer underline"
              onClick={() => void requests.refetch()}
            >
              Spróbuj ponownie
            </button>
          </InlineError>
        )}
        {!requests.isPending && !requests.isError && list.length === 0 && (
          <div className="px-2 py-6">
            <h3 className="m-0 mb-2 text-lg font-semibold">Co warto uwzględnić w Twoim grafiku?</h3>
            <p className="m-0 text-sm text-ink-muted">
              Na przykład: „W piątki wolę pracować rano”. Twoje wiadomości i odpowiedzi pojawią się tutaj.
            </p>
          </div>
        )}
        <ol className="m-0 grid list-none gap-7 p-0">
          {list.map((request) => (
            <li key={request.id} className="grid gap-3">
              <ChatMessage from="user" date={request.created_at}>
                {editable && editing?.id === request.id ? (
                  <form
                    className="grid gap-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      update.mutate(
                        { requestId: request.id, data: { text: editing.text.trim() } },
                        {
                          onSuccess: () => setEditing(null),
                        },
                      )
                    }}
                  >
                    <label className="grid gap-1">
                      Treść prośby
                      <textarea
                        className="rounded-md border-2 border-ink p-2"
                        maxLength={1000}
                        rows={3}
                        value={editing.text}
                        onChange={(e) => setEditing({ id: request.id, text: e.target.value })}
                      />
                    </label>
                    <p className="m-0 text-sm text-ink-muted">
                      Kierownik zobaczy poprawioną treść. Jego wcześniejsza decyzja i nadana prośbie ważność
                      pozostaną w mocy.{' '}
                      {assistantReads &&
                        'Po zmianie tekstu zewnętrzny asystent AI (Claude) przeczyta prośbę ponownie.'}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="submit"
                        disabled={
                          update.isPending || !editing.text.trim() || editing.text.trim() === request.text
                        }
                      >
                        Zapisz prośbę
                      </Button>
                      <Button
                        type="button"
                        variant="quiet"
                        disabled={update.isPending}
                        onClick={() => setEditing(null)}
                      >
                        Anuluj
                      </Button>
                    </div>
                  </form>
                ) : (
                  <p className="m-0 whitespace-pre-wrap">{request.text}</p>
                )}
              </ChatMessage>
              <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-0 text-xs">
                <span className="text-xs text-ink-muted">
                  {request.status === 'answered'
                    ? 'Odpowiedź asystenta'
                    : request.status === 'superseded'
                      ? 'Historia prośby'
                      : 'Wysłane do kierownika'}
                </span>
                {editable &&
                  request.status !== 'superseded' &&
                  editing?.id !== request.id &&
                  removing !== request.id && (
                    <Button
                      variant="quiet"
                      size="normal"
                      aria-label="Edytuj prośbę"
                      className="min-w-(--touch) px-2 text-sm no-underline"
                      onClick={() => setEditing({ id: request.id, text: request.text })}
                    >
                      <Pencil size={18} aria-hidden="true" />
                      <span className="hidden sm:inline">Edytuj prośbę</span>
                    </Button>
                  )}
                {editable &&
                  editing?.id !== request.id &&
                  (removing === request.id ? (
                    <span className="flex flex-wrap items-center justify-end gap-1">
                      <span className="text-sm font-semibold">Usunąć tę prośbę?</span>
                      <Button
                        variant="quiet"
                        size="normal"
                        disabled={remove.isPending}
                        onClick={() =>
                          remove.mutate({ requestId: request.id }, { onSettled: () => setRemoving(null) })
                        }
                      >
                        Tak, usuń
                      </Button>
                      <Button variant="quiet" size="normal" onClick={() => setRemoving(null)}>
                        Nie
                      </Button>
                    </span>
                  ) : (
                    <Button
                      variant="quiet"
                      size="normal"
                      aria-label="Usuń prośbę"
                      className="min-w-(--touch) whitespace-nowrap px-2 text-sm no-underline"
                      onClick={() => setRemoving(request.id)}
                    >
                      <Trash2 size={18} aria-hidden="true" />
                      <span className="hidden sm:inline">Usuń prośbę</span>
                    </Button>
                  ))}
              </div>
              <ChatMessage from="assistant" label={assistantReads ? 'Asystent' : 'Grafikomat'}>
                <RequestStatus
                  request={request}
                  editable={editable && request.status !== 'superseded'}
                  busy={update.isPending}
                  onWrong={() => update.mutate({ requestId: request.id, data: { understood: false } })}
                />
              </ChatMessage>
            </li>
          ))}
        </ol>
      </div>
      <div className="grid gap-3 border-t border-grid p-4">
        {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
        {remove.isError && <InlineError>{errorMessage(remove.error, NETWORK_PROBLEM)}</InlineError>}
        {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
        {editable ? (
          <ChatComposer
            text={text}
            onChange={setText}
            label="Twoja prośba"
            placeholder="Napisz wiadomość…"
            disabled={requests.isPending || requests.isError}
            sending={create.isPending}
            onSend={() => {
              if (!text.trim() || create.isPending) return
              follow.current = true
              create.mutate({ data: { ...params, text: text.trim() } }, { onSuccess: () => setText('') })
            }}
            footer={assistantReads ? 'Prośbę przeczyta też kierownik.' : 'Wiadomość dla kierownika.'}
          />
        ) : (
          <p className="m-0 text-sm text-ink-muted">
            Wiadomości na ten okres są już zamknięte. Jeśli coś się zmieniło, porozmawiaj z kierownikiem.
          </p>
        )}
        {assistantReads && (
          <p className="m-0 text-xs text-ink-muted">
            Claude czyta Twoje wiadomości, dyspozycje i opublikowany grafik.
          </p>
        )}
      </div>
    </section>
  )
}

export function RequestsSection(props: Parameters<typeof RequestsChat>[0]) {
  return <RequestsChat key={`${props.companyId}:${props.periodId ?? props.month}`} {...props} />
}
