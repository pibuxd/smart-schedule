import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Wand2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { GenerationRunOut } from '../../api/generated/model'
import { useGenerateSchedule, useGenerationRun } from '../../api/generated/scheduling/scheduling'
import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
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
          ? 'Grafik ułoży się z dyspozycji, obsady i zasad lokalu. Potrwa to do pół minuty.'
          : 'Każdy lokal ułoży się osobno, z własnymi zasadami. Każdy potrwa do pół minuty.'
      }
    >
      <div className="grid gap-4">
        {early.length > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-prefer-not bg-prefer-not-soft px-3 py-2">
            {one
              ? `Termin dyspozycji jeszcze nie minął, a bez dyspozycji: ${people(early[0].missing)}.`
              : `W ${early.length} lokalach termin jeszcze nie minął, a nie wszyscy wpisali dyspozycje.`}{' '}
            Możesz ułożyć grafik już teraz i ułożyć go ponownie później.
          </p>
        )}
        {missing.length > 0 && early.length === 0 && (
          <p className="m-0">
            Bez dyspozycji:{' '}
            {missing.map((t) => (one ? people(t.missing) : `${t.locationName} (${people(t.missing)})`)).join(', ')}.
            Liczymy ich jak „obojętnie”.
          </p>
        )}
        {manual.length > 0 && (
          <p className="m-0 rounded-sm border-l-4 border-cannot bg-cannot-soft px-3 py-2 text-ink">
            Ułożenie od nowa usunie nieprzypięte ręczne poprawki:{' '}
            {manual.map((t) => (one ? t.manualChanges : `${t.locationName}: ${t.manualChanges}`)).join(', ')}.
            Przypięte zmiany zostaną na miejscu.
          </p>
        )}
        <p className="m-0 text-sm text-ink-muted">
          Wynik zobaczysz jako szkic. Pracownicy zobaczą grafik dopiero, gdy go opublikujesz.
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

/** How a generation is going; polls until it ends, then refreshes the screen's data. */
export function RunProgress({ runId, locationId, compact }: { runId: string; locationId?: string; compact?: boolean }) {
  const queryClient = useQueryClient()
  const run = useGenerationRun(runId, {
    query: {
      refetchInterval: (query) => {
        const data = query.state.data?.data as GenerationRunOut | undefined
        return data && (data.status === 'succeeded' || data.status === 'failed') ? false : POLL_MS
      },
    },
  })
  const data = run.data?.data as GenerationRunOut | undefined
  const finished = data?.status === 'succeeded' || data?.status === 'failed'
  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ predicate: (q) => !String(q.queryKey[0]).includes('generation-runs') })
  }, [finished, queryClient])

  if (run.isError) return <InlineError>{errorMessage(run.error, 'Nie udało się sprawdzić, jak idzie układanie.')}</InlineError>
  if (!data || data.status === 'queued' || data.status === 'running') {
    return (
      <p role="status" className="m-0 flex items-center gap-2 font-semibold text-accent">
        <span className="inline-block size-3 animate-pulse rounded-full bg-accent" aria-hidden="true" />
        {data?.status === 'running' ? 'Układam grafik…' : 'Czekam w kolejce na ułożenie…'}
        {!compact && <span className="font-normal text-ink-muted">To trwa do pół minuty.</span>}
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
