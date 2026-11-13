import { useQueryClient } from '@tanstack/react-query'
import { BellRing } from 'lucide-react'
import { useState } from 'react'

import { useAskForAvailability } from '../../api/generated/scheduling/scheduling'
import type { AskAvailabilityOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'

/**
 * "Poproś o dyspozycje" (everyone) or "Przypomnij" (only those who have not finished): an in-app notice with the
 * period and the deadline. Nothing is arranged automatically; the manager arranges the schedule later, on purpose.
 */
export function AskAvailabilityButton({
  periodId,
  missing,
  asked,
  disabled,
}: {
  periodId: string
  missing: number
  asked: boolean
  disabled?: boolean
}) {
  const ask = useAskForAvailability()
  const queryClient = useQueryClient()
  const [done, setDone] = useState<string | null>(null)
  const remind = asked && missing > 0
  if (asked && missing === 0) return null

  const send = () =>
    ask.mutate(
      { periodId, data: { only_missing: remind } },
      {
        onSuccess: (response) => {
          const { notified } = response.data as AskAvailabilityOut
          setDone(
            notified
              ? `Powiadomienie w aplikacji wysłane (osób: ${notified}). Pracownicy zobaczą je w „Powiadomieniach”, gdy otworzą Grafikomat.`
              : 'Nie ma komu wysłać: nikt nie jest przypisany do tego lokalu.',
          )
          void queryClient.invalidateQueries()
        },
      },
    )

  return (
    <div className="grid content-start gap-2">
      <Button variant={remind ? 'secondary' : 'primary'} size="normal" onClick={send} disabled={disabled || ask.isPending}>
        <BellRing aria-hidden="true" size={20} />
        {remind ? `Przypomnij (${missing})` : 'Poproś o dyspozycje'}
      </Button>
      {done && (
        <p role="status" className="m-0 text-sm text-ink-muted">
          {done}
        </p>
      )}
      {ask.isError && <InlineError>{errorMessage(ask.error, NETWORK_PROBLEM)}</InlineError>}
    </div>
  )
}
