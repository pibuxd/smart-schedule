import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Wand2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { ExperiencedShortOut, GenerationRunOut } from '../../api/generated/model'
import { useCancelGenerationRun, useGenerateSchedule, useGenerationRun } from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, errorStatus, NETWORK_PROBLEM } from '../../lib/api-error'
import { useManager } from './ManagerContext'
import { people, shifts } from './words'

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
  // Positions where one shift needs more experienced people than the location has.
  experiencedShort: ExperiencedShortOut[]
}

/**
 * "Ułóż grafik" (one location) or "Ułóż dla wszystkich" (each location arranged on its own). A deliberate action of
 * the manager: the sheet says who has not answered yet, that it is early when the deadline has not passed, and that
 * unpinned manual changes will be dropped. Nothing is ever arranged by itself.
 */
export function ArrangeButton({
  targets,
  label,
  variant = 'primary',
  disabled,
  onStarted,
}: {
  targets: ArrangeTarget[]
  label?: string
  variant?: 'primary' | 'secondary'
  disabled?: boolean
  onStarted?: (runs: GenerationRunOut[]) => void
}) {
  const [open, setOpen] = useState(false)
  if (targets.length === 0) return null
  const again = targets.length === 1 && targets[0].hasVersion
  return (
    <>
      <Button variant={variant} size="normal" onClick={() => setOpen(true)} disabled={disabled}>
        <Wand2 aria-hidden="true" size={20} />
        {label ?? (again ? 'Ułóż od nowa' : 'Ułóż grafik')}
      </Button>
      <ArrangeSheet open={open} onOpenChange={setOpen} targets={targets} onStarted={onStarted} />
    </>
  )
}

function ArrangeSheet({
  open,
  onOpenChange,
  targets,
  onStarted,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  targets: ArrangeTarget[]
  onStarted?: (runs: GenerationRunOut[]) => void
}) {
  const generate = useGenerateSchedule()
  const queryClient = useQueryClient()
  const one = targets.length === 1
  const early = targets.filter((t) => !t.deadlinePassed && t.missing > 0)
  const missing = targets.filter((t) => t.missing > 0)
  const manual = targets.filter((t) => t.manualChanges > 0)
  const short = targets.filter((t) => t.experiencedShort.length > 0)

  const start = () =>
    generate.mutate(
      { data: { period_ids: targets.map((t) => t.periodId) } },
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
      title={one ? `Ułożyć grafik: ${targets[0].locationName}?` : `Ułożyć grafik dla ${targets.length} lokali?`}
      description={
        one
          ? 'Ułożymy grafik według dyspozycji, obsady i zasad lokalu. To trwa do pół minuty.'
          : 'Każdy lokal układamy osobno, według jego zasad. Każdy trwa do pół minuty.'
      }
    >
      <div className="grid gap-4">
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
                    {row.position_name}: na jednej zmianie potrzeba {row.needed}, a {row.available === 0 ? 'nie masz żadnej' : `masz ${row.available}`}.
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
        </p>
        {generate.isError && <InlineError>{errorMessage(generate.error, NETWORK_PROBLEM)}</InlineError>}
        <Button wide onClick={start} disabled={generate.isPending}>
          {generate.isPending ? 'Zaczynam…' : one ? 'Ułóż grafik' : `Ułóż dla ${targets.length} lokali`}
        </Button>
      </div>
    </Sheet>
  )
}

const POLL_MS = 1500

const ENDED = ['succeeded', 'failed', 'cancelled']

/** How a generation is going, with "Anuluj"; polls until it ends, then refreshes the screen's data. */
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
            {!compact && !cancel.isPending && <span className="font-normal text-ink-muted">To trwa do pół minuty.</span>}
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
