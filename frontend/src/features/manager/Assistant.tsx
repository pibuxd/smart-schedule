import { useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useState } from 'react'

import {
  useApplyAssistantCommand,
  useAssistantCommand,
  useDeleteInstruction,
  useDismissAssistantCommand,
  useLocationInstructions,
  useOrderLocationInstructions,
  useSendAssistantCommand,
} from '../../api/generated/assistant/assistant'
import type { AssistantCommandOut, InstructionOut, InstructionsOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { Tag } from '../../components/ui/field'
import { InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { useManager } from './ManagerContext'

// The assistant answers within seconds; after this long the worker is probably not running.
const WAIT_MS = 90_000

/**
 * "Powiedz asystentowi": the manager writes what should change, the assistant answers with a plan in plain
 * words, and nothing changes until the manager accepts it. Below: the accepted instructions about people,
 * in order of importance.
 */
export function AssistantPanel({ locationId }: { locationId: string }) {
  const { readOnly } = useManager()
  const instructions = useLocationInstructions(locationId)
  const send = useSendAssistantCommand()
  const [text, setText] = useState('')
  const [commandId, setCommandId] = useState<string | null>(null)
  const data = instructions.data?.data as InstructionsOut | undefined
  const enabled = data?.assistant_enabled ?? true

  return (
    <section aria-labelledby="assistant-title" className="grid gap-4 rounded-lg border border-line bg-surface p-5">
      <div className="grid gap-2">
        <h2 id="assistant-title" className="m-0 text-xl font-extrabold">
          Powiedz asystentowi, co zmienić
        </h2>
        <p className="m-0 max-w-[75ch] text-ink-muted">
          Napisz zwykłymi słowami, na przykład: „Ania i Kasia nie na jednej zmianie”, „Marek tylko rano”, „na sali
          zawsze ktoś doświadczony z początkującym” albo „równe weekendy są ważniejsze niż cel godzin”. Asystent
          pokaże, co zmieni w zasadach. Nic się nie zmieni, dopóki tego nie zatwierdzisz. Grafik układa generator,
          nie asystent.
        </p>
      </div>

      {!enabled && (
        <p className="m-0 rounded-sm border border-line bg-paper px-3 py-2 text-ink-muted">
          Asystent jest wyłączony, bo w ustawieniach serwera nie ma klucza do Claude. Zasady możesz ustawić ręcznie na
          liście poniżej, a prośby pracowników przeczytasz sam w „Dyspozycjach”.
        </p>
      )}

      {enabled && (
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (!text.trim()) return
            send.mutate(
              { locationId, data: { text } },
              {
                onSuccess: (response) => {
                  setCommandId((response.data as AssistantCommandOut).id)
                  setText('')
                },
              },
            )
          }}
        >
          <label htmlFor="assistant-text" className="font-semibold">
            Twoje polecenie
          </label>
          <textarea
            id="assistant-text"
            rows={3}
            maxLength={1000}
            value={text}
            disabled={readOnly}
            onChange={(event) => setText(event.target.value)}
            className="min-h-24 rounded-md border-2 border-ink bg-surface p-3 text-base"
          />
          {send.isError && <InlineError>{errorMessage(send.error, NETWORK_PROBLEM)}</InlineError>}
          <div>
            <Button type="submit" disabled={readOnly || send.isPending || !text.trim()}>
              {send.isPending ? 'Wysyłam…' : 'Wyślij asystentowi'}
            </Button>
          </div>
        </form>
      )}

      {commandId && <CommandCard key={commandId} commandId={commandId} onDone={() => setCommandId(null)} />}

      <InstructionList locationId={locationId} loading={instructions.isPending} failed={instructions.isError} data={data} />
    </section>
  )
}

function CommandCard({ commandId, onDone }: { commandId: string; onDone: () => void }) {
  const [started] = useState(() => Date.now())
  const queryClient = useQueryClient()
  const command = useAssistantCommand(commandId, {
    query: {
      refetchInterval: (query) => {
        const now = query.state.data?.data as AssistantCommandOut | undefined
        return now && now.status !== 'queued' ? false : Date.now() - started > WAIT_MS ? false : 1500
      },
    },
  })
  const apply = useApplyAssistantCommand()
  const dismiss = useDismissAssistantCommand()
  const data = command.data?.data as AssistantCommandOut | undefined

  if (command.isError) return <InlineError>{errorMessage(command.error, NETWORK_PROBLEM)}</InlineError>
  if (!data) return <Loading>Asystent czyta polecenie…</Loading>

  const frame = 'grid gap-3 rounded-md border-2 border-accent bg-accent-soft p-4'
  if (data.status === 'queued') {
    const late = Date.now() - started > WAIT_MS
    return (
      <div className={frame} role="status">
        <Quote text={data.text} />
        <p className="m-0">
          {late
            ? 'Asystent nie odpowiada. Spróbuj za chwilę jeszcze raz albo ustaw zasady ręcznie na liście poniżej.'
            : 'Asystent czyta polecenie…'}
        </p>
        {late && (
          <div>
            <Button variant="secondary" size="normal" onClick={onDone}>
              Zamknij
            </Button>
          </div>
        )}
      </div>
    )
  }
  if (data.status === 'failed' || data.status === 'unavailable') {
    return (
      <div className={frame} role="alert">
        <Quote text={data.text} />
        <p className="m-0">
          {data.status === 'failed'
            ? 'Asystent nie dał rady odpowiedzieć. Spróbuj jeszcze raz za chwilę. Nic się nie zmieniło.'
            : 'Asystent jest wyłączony. Ustaw zasady ręcznie na liście poniżej.'}
        </p>
        <div>
          <Button variant="secondary" size="normal" onClick={onDone}>
            Zamknij
          </Button>
        </div>
      </div>
    )
  }
  if (data.status === 'applied' || data.status === 'dismissed') {
    return (
      <div className={frame} role="status">
        <p className="m-0 font-semibold">
          {data.status === 'applied'
            ? 'Zastosowane. Zmiany zadziałają przy następnym układaniu grafiku.'
            : 'Plan odrzucony. Nic się nie zmieniło.'}
        </p>
        <div>
          <Button variant="secondary" size="normal" onClick={onDone}>
            Zamknij
          </Button>
        </div>
      </div>
    )
  }

  const busy = apply.isPending || dismiss.isPending
  const done = { onSuccess: () => void queryClient.invalidateQueries() }
  return (
    <div className={frame}>
      <Quote text={data.text} />
      {data.reply && <p className="m-0">{data.reply}</p>}
      {data.question && <p className="m-0 font-semibold">{data.question}</p>}
      {data.lines.length > 0 && (
        <div className="grid gap-1">
          <h3 className="m-0 text-base font-extrabold">Co się zmieni, jeśli zatwierdzisz</h3>
          <ul className="m-0 grid gap-1 pl-5">
            {data.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {data.effects.length > 0 && (
        <div className="grid gap-1">
          <h3 className="m-0 text-base font-extrabold">Skutek na ostatnim grafiku</h3>
          <ul className="m-0 grid gap-1 pl-5">
            {data.effects.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {data.notes.length > 0 && (
        <ul className="m-0 grid list-none gap-1 p-0">
          {data.notes.map((note) => (
            <li key={note} className="rounded-sm border border-prefer-not bg-prefer-not-soft px-3 py-2 text-sm">
              {note}
            </li>
          ))}
        </ul>
      )}
      {!data.can_apply && !data.question && data.lines.length === 0 && (
        <p className="m-0 text-ink-muted">Asystent nie zaproponował żadnej zmiany. Napisz polecenie inaczej.</p>
      )}
      {(apply.isError || dismiss.isError) && (
        <InlineError>{errorMessage(apply.error ?? dismiss.error, NETWORK_PROBLEM)}</InlineError>
      )}
      <div className="flex flex-wrap gap-3">
        {data.can_apply && (
          <Button disabled={busy} onClick={() => apply.mutate({ commandId }, done)}>
            {apply.isPending ? 'Zapisuję…' : 'Zatwierdź zmiany'}
          </Button>
        )}
        <Button variant="secondary" disabled={busy} onClick={() => dismiss.mutate({ commandId }, done)}>
          {data.can_apply ? 'Odrzuć' : 'Zamknij'}
        </Button>
      </div>
    </div>
  )
}

function Quote({ text }: { text: string }) {
  return <p className="m-0 text-sm text-ink-muted">Twoje polecenie: „{text}”</p>
}

function InstructionList({
  locationId,
  loading,
  failed,
  data,
}: {
  locationId: string
  loading: boolean
  failed: boolean
  data: InstructionsOut | undefined
}) {
  const { readOnly } = useManager()
  const queryClient = useQueryClient()
  const done = { onSuccess: () => void queryClient.invalidateQueries() }
  const order = useOrderLocationInstructions()
  const remove = useDeleteInstruction()
  const busy = readOnly || order.isPending || remove.isPending
  const items: InstructionOut[] = data?.items ?? []
  const move = (from: number, to: number) => {
    const ids = items.map((i) => i.id)
    ids.splice(to, 0, ...ids.splice(from, 1))
    order.mutate({ locationId, data: { ids } }, done)
  }

  return (
    <div className="grid gap-2 border-t border-line pt-4">
      <h3 className="m-0 text-lg font-extrabold">Twoje polecenia o osobach</h3>
      {loading && <Loading>Wczytuję polecenia…</Loading>}
      {failed && <InlineError>Nie udało się wczytać poleceń. Odśwież stronę za chwilę.</InlineError>}
      {data && items.length === 0 && (
        <p className="m-0 text-ink-muted">
          Nie ma jeszcze żadnych. Pojawią się tu polecenia o konkretnych osobach, które zatwierdzisz u asystenta.
        </p>
      )}
      {items.length > 0 && (
        <>
          <p className="m-0 max-w-[75ch] text-sm text-ink-muted">
            Wyżej = ważniejsze. Gdy nie da się spełnić wszystkich, wygrywa polecenie wyżej. Generator stara się je
            spełnić, ale nie zostawi przez nie zmiany bez obsady.
          </p>
          <ol className="m-0 grid list-none gap-2 p-0">
            {items.map((item, index) => (
              <li key={item.id} className="flex flex-wrap items-center gap-3 rounded-md border border-line bg-paper p-3">
                <span className="font-extrabold tabular-nums">{index + 1}.</span>
                <span className="min-w-0 flex-1">{item.text}</span>
                {!item.active && <Tag>minęło</Tag>}
                <span className="flex gap-1">
                  <Button
                    variant="quiet"
                    size="normal"
                    aria-label={`Wyżej: ${item.text}`}
                    disabled={busy || index === 0}
                    onClick={() => move(index, index - 1)}
                  >
                    <ArrowUp aria-hidden size={20} />
                  </Button>
                  <Button
                    variant="quiet"
                    size="normal"
                    aria-label={`Niżej: ${item.text}`}
                    disabled={busy || index === items.length - 1}
                    onClick={() => move(index, index + 1)}
                  >
                    <ArrowDown aria-hidden size={20} />
                  </Button>
                  <Button
                    variant="quiet"
                    size="normal"
                    disabled={busy}
                    aria-label={`Usuń: ${item.text}`}
                    onClick={() => remove.mutate({ instructionId: item.id }, done)}
                  >
                    Usuń
                  </Button>
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
      {(order.isError || remove.isError) && (
        <InlineError>{errorMessage(order.error ?? remove.error, NETWORK_PROBLEM)}</InlineError>
      )}
    </div>
  )
}
