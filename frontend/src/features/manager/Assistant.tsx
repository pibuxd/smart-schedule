import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowDown,
  ArrowUp,
  CalendarCheck,
  Check,
  ChevronDown,
  Clock3,
  Info,
  PanelRight,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import {
  getAssistantHistoryQueryKey,
  useApplyAssistantCommand,
  useAssistantHistory,
  useDeleteInstruction,
  useDismissAssistantCommand,
  useLocationInstructions,
  useOrderLocationInstructions,
  useSendAssistantCommand,
  type assistantHistoryResponse,
} from '../../api/generated/assistant/assistant'
import type { AssistantCommandOut, InstructionOut, InstructionsOut } from '../../api/generated/model'
import { AssistantMark, ChatComposer, ChatMessage, ChatTyping } from '../../components/assistant/Chat'
import { Button } from '../../components/ui/button'
import { Tag } from '../../components/ui/field'
import { InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import { useManager } from './ManagerContext'

const WAIT_MS = 90_000
const STARTERS = [
  { icon: CalendarCheck, title: 'Sprawdź dyspozycje', text: 'Kto nie oddał dyspozycji na najbliższy okres?' },
  {
    icon: Clock3,
    title: 'Podsumuj godziny',
    text: 'Podsumuj godziny pracowników w ostatnim opublikowanym grafiku.',
  },
  {
    icon: SlidersHorizontal,
    title: 'Zmień zasady',
    text: 'Chcę zmienić zasady układania grafiku. Jakie mam możliwości?',
  },
]

/** A persisted conversation. Model memory remains bounded independently of the visible history. */
export function AssistantPanel({ locationId }: { locationId: string }) {
  const { readOnly } = useManager()
  const queryClient = useQueryClient()
  const instructions = useLocationInstructions(locationId)
  const history = useAssistantHistory(locationId, {
    query: {
      refetchInterval: (query) => {
        const result = query.state.data
        return result?.status === 200 &&
          result.data.some(
            (row) => row.status === 'queued' && Date.now() - Date.parse(row.created_at) < WAIT_MS,
          )
          ? 1500
          : false
      },
    },
  })
  const send = useSendAssistantCommand()
  const [text, setText] = useState('')
  const [showInstructions, setShowInstructions] = useState(false)
  const [now, setNow] = useState(Date.now)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const feedRef = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const data = instructions.data?.status === 200 ? instructions.data.data : undefined
  const rows = history.data?.status === 200 ? history.data.data : []
  const enabled = data?.assistant_enabled ?? false
  const pendingUntil = Math.max(
    0,
    ...rows.filter((r) => r.status === 'queued').map((r) => Date.parse(r.created_at) + WAIT_MS),
  )
  const waiting = pendingUntil > now
  const changeKey = rows.map((r) => `${r.id}:${r.status}`).join(',')

  useEffect(() => {
    if (pendingUntil <= Date.now()) return
    const timer = setTimeout(() => setNow(Date.now()), pendingUntil - Date.now() + 20)
    return () => clearTimeout(timer)
  }, [pendingUntil])
  useEffect(() => {
    const feed = feedRef.current
    if (feed && follow.current) feed.scrollTop = feed.scrollHeight
  }, [changeKey, send.isPending])

  const remember = async (row: AssistantCommandOut) => {
    const queryKey = getAssistantHistoryQueryKey(locationId)
    await queryClient.cancelQueries({ queryKey })
    queryClient.setQueryData<assistantHistoryResponse>(queryKey, (old) => ({
      status: 200,
      headers: old?.headers ?? new Headers(),
      data: [...(old?.status === 200 ? old.data : []).filter((r) => r.id !== row.id), row]
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .slice(-50),
    }))
    void queryClient.invalidateQueries()
  }
  const draft = (value: string) => {
    setText(value)
    setShowInstructions(false)
    requestAnimationFrame(() => inputRef.current?.focus())
  }
  const submit = () => {
    if (readOnly || !enabled || send.isPending || waiting || !text.trim()) return
    follow.current = true
    send.mutate(
      { locationId, data: { text: text.trim() } },
      {
        onSuccess: async (response) => {
          if (response.status !== 201) return
          await remember(response.data)
          setText('')
          requestAnimationFrame(() => inputRef.current?.focus())
        },
      },
    )
  }

  return (
    <section
      aria-label="Asystent grafiku"
      className="assistant-shell overflow-hidden rounded-lg border border-line bg-surface shadow-chat"
    >
      <header className="relative flex items-center justify-between gap-2 border-b border-grid px-3 py-3 sm:gap-3 sm:px-6 sm:py-4">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <AssistantMark />
          <div className="min-w-0">
            <h2 className="m-0 text-base font-semibold tracking-tight sm:text-lg">
              Asystent<span className="hidden sm:inline"> grafiku</span>
            </h2>
            <p className="m-0 hidden text-xs text-ink-muted sm:block">
              Mniej układania. Więcej czasu dla zespołu.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <details>
            <summary
              aria-label="Jak działa asystent"
              className="flex min-h-(--touch) w-(--touch) cursor-pointer list-none items-center justify-center rounded-md text-ink-muted hover:bg-paper [&::-webkit-details-marker]:hidden"
            >
              <Info size={20} aria-hidden="true" />
            </summary>
            <div className="absolute inset-x-3 top-full z-20 mt-2 grid gap-3 rounded-md border border-line bg-surface p-4 text-sm shadow-chat sm:right-6 sm:left-auto sm:w-[320px]">
              <b>Ty decydujesz o zmianach</b>
              <p className="m-0">
                Zatwierdzenie zapisuje ustawienia do następnego układania grafiku. Polecenia o osobach są
                preferencjami, bez gwarancji przydziału.
              </p>
              <p className="m-0">
                Claude czyta wiadomości i dane tego lokalu. Pamięta do 6 Twoich poprzednich wiadomości z 24
                godzin. W historii widzisz ostatnie 50.
              </p>
            </div>
          </details>
          <button
            type="button"
            aria-label="Zapisane polecenia"
            aria-expanded={showInstructions}
            onClick={() => setShowInstructions(!showInstructions)}
            className="flex min-h-(--touch) w-(--touch) cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-paper lg:hidden"
          >
            <PanelRight aria-hidden="true" size={20} />
          </button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <div className={cn('min-w-0 flex-1 flex-col', showInstructions ? 'hidden lg:flex' : 'flex')}>
          <div
            ref={feedRef}
            onScroll={() => {
              const f = feedRef.current
              if (f) follow.current = f.scrollHeight - f.scrollTop - f.clientHeight < 100
            }}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-8 sm:py-6"
            role="log"
            aria-label="Rozmowa z asystentem"
            aria-live="polite"
            aria-relevant="additions text"
          >
            {history.isPending && <Loading>Wczytuję rozmowę…</Loading>}
            {history.isError && (
              <div className="grid gap-3">
                <InlineError>{errorMessage(history.error, 'Nie udało się wczytać rozmowy.')}</InlineError>
                <Button variant="secondary" size="normal" onClick={() => void history.refetch()}>
                  Wczytaj ponownie
                </Button>
              </div>
            )}
            {!history.isPending && !history.isError && rows.length === 0 && !send.isPending && (
              <div className="mx-auto flex min-h-full max-w-[42rem] flex-col justify-center gap-4 sm:gap-6 sm:py-8">
                <div>
                  <span className="mb-4 hidden rounded-full sm:inline-flex bg-paper px-3 py-1 text-xs font-semibold tracking-wide text-ink-muted">
                    TWÓJ ZESPÓŁ. DOBRY PLAN.
                  </span>
                  <h3 className="m-0 text-xl font-semibold tracking-tight sm:text-[40px]">
                    W czym mogę pomóc?
                  </h3>
                  <p className="mt-3 mb-0 max-w-[34rem] text-sm leading-relaxed text-ink-muted sm:text-base">
                    Zapytaj o grafik lub opisz zmianę. Resztę ustalimy w rozmowie.
                  </p>
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  {STARTERS.map(({ icon: Icon, title, text }) => (
                    <button
                      key={title}
                      type="button"
                      disabled={!enabled || readOnly}
                      onClick={() => draft(text)}
                      className="group flex min-h-(--touch-main) cursor-pointer items-center gap-3 rounded-md border border-grid bg-surface p-3 text-left transition-colors hover:border-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-60 sm:flex-col sm:items-start sm:gap-4 sm:p-4"
                    >
                      <Icon size={22} strokeWidth={1.6} className="shrink-0 text-accent" aria-hidden="true" />
                      <span className="text-sm font-medium">{title}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <ol className="m-0 mx-auto grid max-w-[48rem] list-none gap-8 p-0">
              {rows.map((row, i) => (
                <li key={row.id} className="grid gap-5">
                  {(i === 0 ||
                    new Date(row.created_at).toLocaleDateString('pl-PL') !==
                      new Date(rows[i - 1].created_at).toLocaleDateString('pl-PL')) && (
                    <p className="m-0 text-center text-xs text-ink-muted">
                      {new Date(row.created_at).toLocaleDateString('pl-PL', {
                        day: 'numeric',
                        month: 'long',
                        year: 'numeric',
                      })}
                    </p>
                  )}
                  <ChatMessage from="user" date={row.created_at}>
                    <p className="m-0 whitespace-pre-wrap">{row.text}</p>
                  </ChatMessage>
                  <ChatMessage from="assistant">
                    <CommandReply
                      data={row}
                      late={now - Date.parse(row.created_at) >= WAIT_MS}
                      readOnly={readOnly}
                      onChanged={remember}
                      onRetry={() => void history.refetch()}
                      onRewrite={() => draft(row.text)}
                    />
                  </ChatMessage>
                </li>
              ))}
              {send.isPending && (
                <li className="grid gap-5">
                  <ChatMessage from="user">
                    <p className="m-0 whitespace-pre-wrap">{send.variables?.data.text}</p>
                  </ChatMessage>
                  <ChatMessage from="assistant">
                    <ChatTyping>Wysyłam wiadomość…</ChatTyping>
                  </ChatMessage>
                </li>
              )}
            </ol>
          </div>
          <div className="shrink-0 border-t border-grid bg-surface px-4 pt-4 pb-3 sm:px-6">
            {send.isError && (
              <div className="mb-3">
                <InlineError>
                  {errorMessage(send.error, NETWORK_PROBLEM)} Tekst pozostał w polu wiadomości.
                </InlineError>
              </div>
            )}
            {instructions.isError && (
              <InlineError>
                Nie udało się sprawdzić dostępności asystenta.{' '}
                <button
                  type="button"
                  className="min-h-(--touch) cursor-pointer underline"
                  onClick={() => void instructions.refetch()}
                >
                  Spróbuj ponownie
                </button>
              </InlineError>
            )}
            {data && !enabled && (
              <p className="mt-0 text-sm text-ink-muted">
                Asystent jest wyłączony. Możesz przejrzeć rozmowę i zmienić zasady ręcznie.
              </p>
            )}
            {readOnly && <p className="mt-0 text-sm text-ink-muted">Masz dostęp tylko do odczytu.</p>}
            <ChatComposer
              text={text}
              onChange={setText}
              onSend={submit}
              sending={send.isPending}
              waiting={waiting}
              inputRef={inputRef}
              disabled={readOnly || !enabled || history.isPending || history.isError}
              footer="Zmiany wymagają zatwierdzenia."
            />
            <p className="mt-2 mb-0 text-center text-xs text-ink-muted">
              Rozmawiasz z AI. Claude czyta wiadomości i dane tego lokalu.
            </p>
          </div>
        </div>
        <aside
          aria-label="Zapisane polecenia o osobach"
          className={cn(
            'w-full shrink-0 flex-col overflow-y-auto bg-paper p-5 lg:w-[300px] lg:border-l lg:border-grid',
            showInstructions ? 'flex' : 'hidden lg:flex',
          )}
        >
          <div className="mb-4 flex items-center gap-2 text-xs font-semibold tracking-wide text-ink-muted">
            <SlidersHorizontal aria-hidden="true" size={16} /> USTAWIENIA GRAFIKU
          </div>
          <InstructionList
            locationId={locationId}
            loading={instructions.isPending}
            failed={instructions.isError}
            data={data}
          />
          <div className="mt-auto border-t border-grid pt-5 text-sm text-ink-muted">
            <p className="m-0 mb-2">Chcesz zajrzeć do wszystkich zasad?</p>
            <Link
              to="/kierownik/lokal/$locationId/zasady"
              params={{ locationId }}
              className="inline-flex min-h-(--touch) items-center gap-2 font-semibold text-accent no-underline"
            >
              Otwórz zasady <ArrowUp size={16} className="rotate-45" aria-hidden="true" />
            </Link>
          </div>
        </aside>
      </div>
    </section>
  )
}

function CommandReply({
  data,
  late,
  readOnly,
  onChanged,
  onRetry,
  onRewrite,
}: {
  data: AssistantCommandOut
  late: boolean
  readOnly: boolean
  onChanged: (row: AssistantCommandOut) => Promise<void>
  onRetry: () => void
  onRewrite: () => void
}) {
  const apply = useApplyAssistantCommand()
  const dismiss = useDismissAssistantCommand()
  if (data.status === 'queued')
    return late ? (
      <div className="grid gap-2">
        <p className="m-0">Odpowiedź zajmuje więcej czasu niż zwykle.</p>
        <div>
          <Button variant="secondary" size="normal" onClick={onRetry}>
            Sprawdź odpowiedź
          </Button>
        </div>
      </div>
    ) : (
      <ChatTyping />
    )
  if (data.status === 'failed' || data.status === 'unavailable')
    return (
      <div className="grid gap-3">
        <p role="alert" className="m-0">
          {data.status === 'failed'
            ? 'Nie udało się przygotować odpowiedzi. Nic się nie zmieniło.'
            : 'Asystent jest teraz niedostępny. Spróbuj później.'}
        </p>
        <div>
          <Button variant="secondary" size="normal" disabled={readOnly} onClick={onRewrite}>
            Wpisz ponownie
          </Button>
        </div>
      </div>
    )
  const applied = data.status === 'applied'
  const dismissed = data.status === 'dismissed'
  const busy = readOnly || apply.isPending || dismiss.isPending
  const done = {
    onSuccess: async (response: { status: number; data: unknown }) => {
      if (response.status === 200) await onChanged(response.data as AssistantCommandOut)
    },
  }
  return (
    <>
      {data.reply && <p className="m-0 whitespace-pre-wrap">{data.reply}</p>}
      {data.question && <p className="m-0 font-semibold">{data.question}</p>}
      {data.lines.length > 0 && (
        <div className="overflow-hidden rounded-md border border-grid">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-grid bg-paper px-4 py-3">
            <span className="text-sm font-semibold">Propozycja zmian</span>
            {applied ? (
              <span className="flex items-center gap-1 whitespace-nowrap text-xs font-semibold text-prefer">
                <Check size={16} aria-hidden="true" /> Zatwierdzona
              </span>
            ) : dismissed ? (
              <span className="flex items-center gap-1 whitespace-nowrap text-xs text-ink-muted">
                <X size={16} aria-hidden="true" /> Odrzucona
              </span>
            ) : (
              <span className="text-xs text-ink-muted">Do zatwierdzenia</span>
            )}
          </div>
          <ul className="m-0 grid list-none gap-3 p-4">
            {data.lines.map((line, i) => (
              <li key={`${i}:${line}`} className="flex gap-3">
                <span
                  aria-hidden="true"
                  className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
                >
                  {i + 1}
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
          {data.can_apply && data.status === 'ready' && (
            <div className="flex flex-wrap gap-2 border-t border-grid px-4 py-3">
              <Button
                size="normal"
                disabled={busy}
                onClick={() => apply.mutate({ commandId: data.id }, done)}
              >
                <Check size={18} aria-hidden="true" />
                {apply.isPending ? 'Zapisuję…' : 'Zatwierdź zmiany'}
              </Button>
              <Button
                variant="quiet"
                size="normal"
                disabled={busy}
                onClick={() => dismiss.mutate({ commandId: data.id }, done)}
              >
                Odrzuć
              </Button>
            </div>
          )}
        </div>
      )}
      {applied && (
        <p role="status" className="m-0 text-sm text-prefer">
          Ustawienia zapisane. Zostaną uwzględnione przy następnym układaniu grafiku.
        </p>
      )}
      {dismissed && (
        <p role="status" className="m-0 text-sm text-ink-muted">
          Propozycja odrzucona. Ustawienia pozostały bez zmian.
        </p>
      )}
      {data.notes.length > 0 && (
        <ul className="m-0 grid list-none gap-2 rounded-md bg-prefer-not-soft p-3 text-sm text-prefer-not">
          {data.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
      {data.effects.length > 0 && (
        <details className="text-sm text-ink-muted">
          <summary className="flex min-h-(--touch) cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
            <ChevronDown size={16} aria-hidden="true" /> Wpływ na ostatni grafik
          </summary>
          <ul className="mt-0 grid gap-2 pl-5">
            {data.effects.map((effect, i) => (
              <li key={i}>{effect}</li>
            ))}
          </ul>
        </details>
      )}
      {!data.reply && !data.question && !data.lines.length && !applied && !dismissed && (
        <p className="m-0 text-ink-muted">Nie mam jeszcze propozycji. Opisz dokładniej, co chcesz zmienić.</p>
      )}
      {(apply.isError || dismiss.isError) && (
        <InlineError>{errorMessage(apply.error ?? dismiss.error, NETWORK_PROBLEM)}</InlineError>
      )}
    </>
  )
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
    <div className="mb-6 grid gap-3">
      <h3 className="m-0 flex items-center justify-between gap-2 text-base font-semibold">
        Zapisane polecenia{' '}
        <span className="rounded-full border border-line px-2 text-xs tabular-nums">{items.length}</span>
      </h3>
      {loading && <Loading>Wczytuję polecenia…</Loading>}
      {failed && <InlineError>Nie udało się wczytać poleceń. Odśwież stronę za chwilę.</InlineError>}
      {data && items.length === 0 && (
        <p className="m-0 text-sm leading-relaxed text-ink-muted">
          Nie ma jeszcze żadnych. Pojawią się tu polecenia o konkretnych osobach, które zatwierdzisz u
          asystenta.
        </p>
      )}
      {items.length > 0 && (
        <>
          <p className="m-0 max-w-[75ch] text-sm text-ink-muted">
            Wyżej = ważniejsze. Gdy nie da się spełnić wszystkich, wygrywa polecenie wyżej. Generator stara
            się je spełnić, ale nie zostawi przez nie zmiany bez obsady.
          </p>
          <ol className="m-0 grid list-none gap-2 p-0">
            {items.map((item, index) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center gap-2 rounded-md border border-grid bg-surface p-3 text-sm"
              >
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
