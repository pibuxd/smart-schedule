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
  if (request.status === 'interpreted' && request.summary) {
    return (
      <div className="grid gap-2 rounded-sm bg-accent-soft p-3">
        <p className="m-0">
          <span className="font-semibold">Tak to zrozumieliśmy: </span>
          {request.summary}
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
  if (request.status === 'new') return <p className="m-0 text-sm text-ink-muted">Czytamy Twoją prośbę…</p>
  return <p className="m-0 text-sm text-ink-muted">Kierownik przeczyta tę prośbę sam.</p>
}

/** "Coś jeszcze?": a request in words, only for what the calendar cannot say. Only the manager reads it. */
export function RequestsSection({
  companyId,
  periodId,
  editable,
}: {
  companyId: string
  periodId: string
  editable: boolean
}) {
  const params = { company_id: companyId, period_id: periodId }
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
  const update = useUpdateMyRequest({ mutation: { onSuccess: refresh } })
  const [text, setText] = useState('')
  const list = (requests.data?.data as MyRequestOut[] | undefined) ?? []

  return (
    <section aria-labelledby="requests-title" className="grid gap-3 border-t border-line pt-5">
      <h2 id="requests-title" className="m-0 text-lg font-extrabold">
        Coś jeszcze?
      </h2>
      <p className="m-0 text-sm text-ink-muted">
        Napisz to, czego nie da się zaznaczyć w kalendarzu, na przykład w które dni wolisz mieć wolne albo z kim nie
        chcesz mieć zmiany. Jedna prośba, jedna sprawa. Napisz też powód, jeśli jest ważny. Prośbę zobaczy tylko
        kierownik.
      </p>
      {requests.isError && <InlineError>Nie udało się wczytać Twoich próśb. Odśwież stronę za chwilę.</InlineError>}
      {list.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {list.map((request) => (
            <li key={request.id} className="grid gap-2 rounded-md border border-line bg-surface p-3.5">
              <p className="m-0">{request.text}</p>
              <RequestStatus
                request={request}
                editable={editable}
                busy={update.isPending}
                onWrong={() => update.mutate({ requestId: request.id, data: { understood: false } })}
              />
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-ink-muted">Wysłane do kierownika</span>
                {editable && (
                  <Button
                    variant="quiet"
                    size="normal"
                    className="whitespace-nowrap"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate({ requestId: request.id })}
                  >
                    Usuń prośbę
                  </Button>
                )}
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
            {create.isPending ? 'Wysyłam…' : 'Wyślij prośbę do kierownika'}
          </Button>
        </form>
      )}
    </section>
  )
}
