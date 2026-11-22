import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { MessageCircle, Shuffle, Wand2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useSubscription } from '../../api/generated/billing/billing'
import type { ExperiencedShortOut, GenerationRunOut, SubscriptionOut } from '../../api/generated/model'
import { useCancelGenerationRun, useGenerateSchedule, useGenerationRun } from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, errorStatus, NETWORK_PROBLEM } from '../../lib/api-error'
import { useAssistantDrawer } from './assistant-drawer'
import { useManager } from './ManagerContext'
import { people, shifts, shortDay } from './words'

/** One location's period, as the "Ułóż grafik" sheet needs it. */
export type ArrangeTarget = {
  periodId: string
  locationId: string
  locationName: string
  // People without availability yet (they count as "obojętnie").
  missing: number
  deadlinePassed: boolean
  // Manual changes in the newest version that arranging again drops (pins stay).
  manualChanges: number
  hasVersion: boolean
  // A published period: its agreements are closed, so the chat cannot arrange it (only the buttons can).
  published?: boolean
  // Positions where one shift needs more experienced people than the location has.
  experiencedShort: ExperiencedShortOut[]
}

/**
 * "Ułóż grafik" (one location) or "Ułóż dla wszystkich" (each location arranged on its own). A deliberate action of
 * the manager: the sheet says who has not answered yet, that it is early when the deadline has not passed, and that
 * unpinned manual changes will be dropped. Nothing is ever arranged by itself.
 * `different` is "Ułóż inaczej": a new schedule that gives about every third shift to someone else than each earlier
 * version did (docs/plan.md section 36).
 */
export function ArrangeButton({
  targets,
  label,
  variant = 'primary',
  disabled,
  different = false,
  onStarted,
}: {
  targets: ArrangeTarget[]
  label?: string
  variant?: 'primary' | 'secondary'
  disabled?: boolean
  different?: boolean
  onStarted?: (runs: GenerationRunOut[]) => void
}) {
  const [open, setOpen] = useState(false)
  if (targets.length === 0) return null
  const again = targets.length === 1 && targets[0].hasVersion
  const Icon = different ? Shuffle : Wand2
  return (
    <>
      <Button variant={variant} size="normal" onClick={() => setOpen(true)} disabled={disabled}>
        <Icon aria-hidden="true" size={20} />
        {label ?? (different ? 'Ułóż inaczej' : again ? 'Ułóż od nowa' : 'Ułóż grafik')}
      </Button>
      <ArrangeSheet
        open={open}
        onOpenChange={setOpen}
        targets={targets}
        different={different}
        onStarted={onStarted}
      />
    </>
  )
}

function ArrangeSheet({
  open,
  onOpenChange,
  targets,
  different,
  onStarted,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  targets: ArrangeTarget[]
  different: boolean
  onStarted?: (runs: GenerationRunOut[]) => void
}) {
  const generate = useGenerateSchedule()
  const queryClient = useQueryClient()
  const chat = useAssistantDrawer()
  const { companyId } = useManager()
  const subscription = useSubscription(companyId, { query: { enabled: open, staleTime: 60_000 } })
  const usage = subscription.data?.data as SubscriptionOut | undefined
  // The company's monthly limit counts every arranging, "Ułóż inaczej" too: say what is left before the click.
  const limit = typeof usage?.generations_limit === 'number' && usage.generations_limit > 0 ? usage.generations_limit : 0
  const left = limit && usage ? Math.max(0, limit - usage.generations_used) : 0
  const one = targets.length === 1
  const early = targets.filter((t) => !t.deadlinePassed && t.missing > 0)
  const missing = targets.filter((t) => t.missing > 0)
  const manual = targets.filter((t) => t.manualChanges > 0)
  const short = targets.filter((t) => t.experiencedShort.length > 0)

  const start = () =>
    generate.mutate(
      { data: { period_ids: targets.map((t) => t.periodId), ...(different ? { different: true } : {}) } },
      {
        onSuccess: (response) => {
          void queryClient.invalidateQueries()
          onStarted?.(response.data as GenerationRunOut[])
          onOpenChange(false)
        },
      },
    )

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={
        different
          ? 'Ułożyć inny grafik?'
          : one
            ? `Ułożyć grafik dla lokalu ${targets[0].locationName}?`
            : `Ułożyć grafik dla ${targets.length} lokali?`
      }
      description={one ? 'Trwa do pół minuty.' : 'Każdy lokal trwa do pół minuty.'}
    >
      <div className="grid gap-4">
        {different && (
          <p className="m-0">
            Co trzecia zmiana dostanie inną osobę niż we wcześniejszych wersjach, o ile się da. Zmian bez obsady nie
            przybędzie, ale zasady i prośby mogą wyjść trochę słabiej.
          </p>
        )}
        {early.length > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
            {one
              ? `Termin dyspozycji jeszcze nie minął. Czekasz jeszcze na: ${people(early[0].missing)}.`
              : `W ${early.length} lokalach termin jeszcze nie minął, a nie wszyscy wpisali dyspozycje.`}{' '}
            Możesz ułożyć grafik już teraz, a potem jeszcze raz.
          </p>
        )}
        {missing.length > 0 && early.length === 0 && (
          <p className="m-0">
            Dyspozycji nie wysłali:{' '}
            {missing.map((t) => (one ? people(t.missing) : `${t.locationName} (${people(t.missing)})`)).join(', ')}.
            Przyjmiemy, że mogą pracować każdego dnia.
          </p>
        )}
        {manual.length > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-cannot bg-cannot-soft px-3 py-2 text-ink">
            Stracisz ręczne poprawki bez przypięcia:{' '}
            {manual.map((t) => (one ? t.manualChanges : `${t.locationName}: ${t.manualChanges}`)).join(', ')}.
            Przypięte zmiany zostaną.
          </p>
        )}
        {short.length > 0 && (
          <div className="grid gap-1 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
            <p className="m-0 font-semibold">Masz za mało doświadczonych osób.</p>
            <ul className="m-0 grid gap-1 pl-5">
              {short.flatMap((t) =>
                t.experiencedShort.map((row) => (
                  <li key={`${t.periodId}-${row.position_id}`}>
                    {one ? '' : `${t.locationName}, `}
                    {row.position_name}: zmiana {row.shift_name} ({shortDay(row.day)}) potrzebuje {row.needed}, a w tym lokalu {row.available === 0 ? 'nie masz żadnej' : `masz ${row.available}`}.
                  </li>
                )),
              )}
            </ul>
            <p className="m-0">
              Te miejsca w grafiku zostaną wolne. Możesz najpierw zmienić stopień w „Pracownicy” albo obsadę w
              „Ustawienia lokalu”.
            </p>
          </div>
        )}
        <p className="m-0 text-sm text-ink-muted">
          Dostaniesz szkic do poprawek. Pracownicy zobaczą grafik dopiero, gdy go opublikujesz.
          {different &&
            ` Gdy nowy będzie gorszy, usuń go koszem, a wróci obecny${manual.length > 0 ? ' razem z poprawkami' : ''}.`}
        </p>
        {limit > 0 && (
          <p
            className={
              left < targets.length
                ? 'm-0 rounded-sm border-l-4 border-cannot bg-cannot-soft px-3 py-2 text-ink'
                : 'm-0 text-sm text-ink-muted'
            }
          >
            Zostało ułożeń w tym miesiącu: {left} z {limit}.
            {left < targets.length && ' Nowe będą możliwe od pierwszego dnia kolejnego miesiąca.'}
          </p>
        )}
        {generate.isError && <InlineError>{errorMessage(generate.error, NETWORK_PROBLEM)}</InlineError>}
        <Button wide onClick={start} disabled={generate.isPending}>
          {generate.isPending
            ? 'Zaczynam…'
            : different
              ? 'Ułóż inny grafik'
              : one
                ? 'Ułóż grafik'
                : `Ułóż dla ${targets.length} lokali`}
        </Button>
        {different && one && chat && !targets[0].published && (
          <Button
            variant="quiet"
            size="normal"
            onClick={() => {
              onOpenChange(false)
              chat.openChat({
                locationId: targets[0].locationId,
                periodId: targets[0].periodId,
                text: 'Ułóż inny grafik, żeby ',
              })
            }}
          >
            <MessageCircle aria-hidden="true" size={18} />
            Napisz asystentowi, co ma być inaczej
          </Button>
        )}
      </div>
    </Sheet>
  )
}

const POLL_MS = 1500

const ENDED = ['succeeded', 'failed', 'cancelled']

/** How a generation is going, with "Anuluj"; polls until it ends, then refreshes the screen's data. */
// Arranging usually takes under half a minute; after this long the screen says so instead of waiting silently.
const SLOW_RUN_MS = 2 * 60 * 1000

/** True once `since` (an ISO time) is more than SLOW_RUN_MS ago; re-checked every few seconds. */
function useTookLong(since: string | null): boolean {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!since) return
    const timer = window.setInterval(() => setNow(Date.now()), 5000)
    return () => window.clearInterval(timer)
  }, [since])
  return since !== null && now - new Date(since).getTime() > SLOW_RUN_MS
}

export function RunProgress({ runId, locationId, compact }: { runId: string; locationId?: string; compact?: boolean }) {
  const queryClient = useQueryClient()
  const { readOnly } = useManager()
  const cancel = useCancelGenerationRun()
  const run = useGenerationRun(runId, {
    query: {
      refetchInterval: (query) => {
        const data = query.state.data?.data as GenerationRunOut | undefined
        return data && ENDED.includes(data.status) ? false : POLL_MS
      },
    },
  })
  const data = run.data?.data as GenerationRunOut | undefined
  const finished = data !== undefined && ENDED.includes(data.status)
  const slow = useTookLong(data && !finished ? data.created_at : null)
  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ predicate: (q) => !String(q.queryKey[0]).includes('generation-runs') })
  }, [finished, queryClient])

  if (run.isError) return <InlineError>{errorMessage(run.error, 'Nie udało się sprawdzić, czy grafik jest już ułożony.')}</InlineError>
  if (!data || data.status === 'queued' || data.status === 'running') {
    // A 409 means the run ended a moment ago: the next poll shows its result, so it is not an error to show.
    const cancelFailed = cancel.isError && errorStatus(cancel.error) !== 409
    return (
      <div className="grid justify-items-start gap-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p role="status" className="m-0 flex items-center gap-2 font-semibold text-accent">
            <span className="inline-block size-3 animate-pulse rounded-full bg-accent" aria-hidden="true" />
            {cancel.isPending
              ? 'Anuluję…'
              : data?.status === 'running'
                ? 'Układam grafik…'
                : 'Grafik czeka w kolejce…'}
            {!compact && !cancel.isPending && !slow && <span className="font-normal text-ink-muted">To trwa do pół minuty.</span>}
          </p>
          {!readOnly && (
            <Button
              variant="quiet"
              size="normal"
              disabled={cancel.isPending || cancel.isSuccess}
              onClick={() =>
                cancel.mutate({ runId }, { onSettled: () => void queryClient.invalidateQueries() })
              }
            >
              Anuluj
            </Button>
          )}
        </div>
        {slow && !cancel.isPending && (
          <p className="m-0 text-sm text-ink-muted">
            Trwa dłużej niż zwykle. Możesz poczekać albo nacisnąć „Anuluj” i spróbować za chwilę.
          </p>
        )}
        {cancelFailed && <InlineError>{errorMessage(cancel.error, NETWORK_PROBLEM)}</InlineError>}
      </div>
    )
  }
  if (data.status === 'cancelled') {
    return (
      <p role="status" className="m-0 font-semibold">
        Anulowane. Nic się nie zmieniło.
      </p>
    )
  }
  if (data.status === 'failed') {
    return (
      <div role="alert" className="grid gap-1 rounded-sm bg-cannot-soft px-3 py-2 text-cannot">
        <span className="font-semibold">Nie udało się ułożyć grafiku.</span>
        {data.error.split('\n').map((line) => (
          <span key={line}>{line}</span>
        ))}
      </div>
    )
  }
  const version = data.versions[0]
  return (
    <p role="status" className="m-0 font-semibold">
      Grafik ułożony
      {version &&
        (version.scores.holes > 0 ? `, ale bez obsady: ${shifts(version.scores.holes)}.` : '.')}{' '}
      {locationId && (
        <Link
          to="/kierownik/lokal/$locationId/grafik"
          params={{ locationId }}
          className="text-accent underline underline-offset-4"
        >
          Zobacz szkic
        </Link>
      )}
    </p>
  )
}
