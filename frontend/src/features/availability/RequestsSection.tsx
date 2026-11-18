import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  getMyRequestsQueryKey,
  useCreateMyRequest,
  useDeleteMyRequest,
  useMyRequests,
  useUpdateMyRequest,
} from '../../api/generated/availability/availability'
import type { MyRequestOut } from '../../api/generated/model'
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
    return <p className="m-0 text-sm text-ink-muted">Ta prośba została zastąpiona nowszą. Nie wpływa już na układanie grafiku.</p>
  }
  if (request.status === 'answered' && request.summary) {
    return (
      <div className="grid gap-2 rounded-sm bg-accent-soft p-3">
        <p className="m-0">{request.summary}</p>
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
      <div className="grid gap-2 rounded-sm bg-accent-soft p-3">
        <p className="m-0">
          <span className="font-semibold">Tak to zrozumieliśmy: </span>
          {request.summary}
        </p>
        <p className="m-0 text-sm">To preferencja, którą generator spróbuje spełnić. Nie zmienia kalendarza dyspozycji. Jeśli nie możesz pracować, zaznacz „nie mogę” w kalendarzu.</p>
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
  if (request.status === 'new') return <p className="m-0 text-sm text-ink-muted">Czytamy Twoją prośbę…</p>
  return <p className="m-0 text-sm text-ink-muted">Kierownik przeczyta tę prośbę sam.</p>
}

/**
 * "Coś jeszcze?": a request in words, only for what the calendar cannot say. The manager reads it; when the
 * assistant is on (`assistantReads`), the text also goes to an outside AI service, and the screen says so.
 * It belongs to the period the manager asked for (`periodId`), or, before that, to the month on the screen
 * (`month`, its first day): the manager sees it in every period that covers that month.
 */
export function RequestsSection({
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

  return (
    <section aria-labelledby="requests-title" className="grid gap-3 border-t border-line pt-5">
      <h2 id="requests-title" className="m-0 text-lg font-extrabold">
        Coś jeszcze?
      </h2>
      <p className="m-0 text-sm text-ink-muted">
        Napisz to, czego nie zaznaczysz w kalendarzu. Na przykład: w które dni wolisz mieć wolne albo z kim nie chcesz
        pracować. Jedna prośba, jedna sprawa. Napisz też powód, jeśli jest ważny.{' '}
        {!periodId && 'Prośba dotyczy tego miesiąca. Kierownik weźmie ją pod uwagę, gdy będzie układać na niego grafik. '}
        {assistantReads
          ? 'Asystent AI (zewnętrzna usługa Claude) czyta tę wiadomość, Twoje wcześniejsze prośby, dyspozycje i opublikowany grafik ze współpracownikami na Twoich zmianach. Możesz zapytać o te dane lub poprawić wcześniejszą prośbę. Prośby czyta też kierownik. Asystent nie układa grafiku ani nie zmienia kalendarza. Nie wpisuj tu nic, czego nie chcesz mu przekazać.'
          : 'Przeczyta to tylko kierownik.'}
      </p>
      {requests.isError && <InlineError>Nie udało się wczytać Twoich próśb. Spróbuj za chwilę.</InlineError>}
      {list.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {list.map((request) => (
            <li key={request.id} className="grid gap-2 rounded-md border border-line bg-surface p-3.5">
              {editable && editing?.id === request.id ? (
                <form className="grid gap-2" onSubmit={(event) => {
                  event.preventDefault()
                  update.mutate({ requestId: request.id, data: { text: editing.text.trim() } }, {
                    onSuccess: () => setEditing(null),
                  })
                }}>
                  <label className="grid gap-1">Treść prośby
                    <textarea className="rounded-md border-2 border-ink p-2" maxLength={1000} rows={3}
                      value={editing.text} onChange={(e) => setEditing({ id: request.id, text: e.target.value })} />
                  </label>
                  <p className="m-0 text-sm text-ink-muted">
                    Kierownik zobaczy poprawioną treść. Jego wcześniejsza decyzja i nadana prośbie ważność pozostaną w mocy.{' '}
                    {assistantReads && 'Po zmianie tekstu zewnętrzny asystent AI (Claude) przeczyta prośbę ponownie.'}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" disabled={update.isPending || !editing.text.trim() || editing.text.trim() === request.text}>Zapisz prośbę</Button>
                    <Button type="button" variant="quiet" disabled={update.isPending} onClick={() => setEditing(null)}>Anuluj</Button>
                  </div>
                </form>
              ) : <p className="m-0">{request.text}</p>}
              <RequestStatus
                request={request}
                editable={editable && request.status !== 'superseded'}
                busy={update.isPending}
                onWrong={() => update.mutate({ requestId: request.id, data: { understood: false } })}
              />
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm text-ink-muted">{request.status === 'answered' ? 'Odpowiedź asystenta' : request.status === 'superseded' ? 'Historia prośby' : 'Wysłane do kierownika'}</span>
                {editable && request.status !== 'superseded' && editing?.id !== request.id && removing !== request.id && (
                  <Button variant="quiet" size="normal" onClick={() => setEditing({ id: request.id, text: request.text })}>
                    Edytuj prośbę
                  </Button>
                )}
                {editable && editing?.id !== request.id &&
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
                      className="whitespace-nowrap"
                      onClick={() => setRemoving(request.id)}
                    >
                      Usuń prośbę
                    </Button>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (!text.trim()) return
            create.mutate({ data: { ...params, text } }, { onSuccess: () => setText('') })
          }}
        >
          <label htmlFor="request-text" className="sr-only">
            Twoja prośba
          </label>
          <textarea
            id="request-text"
            rows={3}
            maxLength={1000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Na przykład: proszę nie dawać mi dwóch nocek pod rząd."
            className="min-h-24 rounded-md border-2 border-ink bg-surface p-3 text-base"
          />
          {update.isError && <InlineError>{errorMessage(update.error, NETWORK_PROBLEM)}</InlineError>}
          {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
          <Button variant="secondary" type="submit" wide disabled={create.isPending || !text.trim()}>
            {create.isPending ? 'Wysyłam…' : 'Wyślij prośbę'}
          </Button>
        </form>
      )}
    </section>
  )
}
