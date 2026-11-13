import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { useCancelMyOffer, useOfferMyShift } from '../../api/generated/marketplace/marketplace'
import type { MyShiftOut, OfferMadeOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayTitle, parseDate, shortTime } from '../../lib/dates'

/**
 * "Oddaj zmianę": everyone who could take the shift gets a notification; the shift stays mine until the manager
 * approves someone. While it is being given away, "Zostaję na tej zmianie" takes the offer back.
 */
export function GiveAwaySheet({ shift, onClose }: { shift: MyShiftOut | null; onClose: () => void }) {
  return (
    <Sheet
      open={shift !== null}
      onOpenChange={(open) => !open && onClose()}
      title={shift?.offer_status ? 'Oddajesz tę zmianę' : 'Oddać tę zmianę?'}
      description={
        shift
          ? `${dayTitle(parseDate(shift.date))}, ${shortTime(shift.start_time)}–${shortTime(shift.end_time)}, ${shift.position_name}`
          : undefined
      }
    >
      {shift && <GiveAway key={shift.id} shift={shift} onClose={onClose} />}
    </Sheet>
  )
}

function GiveAway({ shift, onClose }: { shift: MyShiftOut; onClose: () => void }) {
  const offer = useOfferMyShift()
  const cancel = useCancelMyOffer()
  const queryClient = useQueryClient()
  const [sent, setSent] = useState<number | null>(null)
  const refresh = () => void queryClient.invalidateQueries()

  if (sent !== null) {
    return (
      <div className="grid gap-4">
        <p role="status" className="m-0">
          {sent > 0
            ? `Powiadomienie dostały osoby, które mogą wziąć tę zmianę (liczba osób: ${sent}). Gdy ktoś zechce ją wziąć, kierownik zdecyduje, a Ty dostaniesz powiadomienie.`
            : 'Nikt inny nie może teraz wziąć tej zmiany (inne zmiany, „nie mogę” albo inne stanowisko). Zostaje oddawana: jeśli ktoś się zwolni, zobaczy ją w „Zmiany do wzięcia”. Możesz też porozmawiać z kierownikiem.'}
        </p>
        <p className="m-0 font-semibold">Do decyzji kierownika to nadal Twoja zmiana.</p>
        <Button wide onClick={onClose}>
          Rozumiem
        </Button>
      </div>
    )
  }

  if (shift.offer_id) {
    return (
      <div className="grid gap-4">
        <p className="m-0">
          {shift.offer_status === 'claimed'
            ? 'Ktoś chce wziąć tę zmianę. Czekamy na decyzję kierownika.'
            : 'Czekamy, aż ktoś zechce wziąć tę zmianę.'}
        </p>
        <p className="m-0 font-semibold">Do decyzji kierownika to nadal Twoja zmiana: przyjdź na nią, jeśli nic się nie zmieni.</p>
        {cancel.isError && <InlineError>{errorMessage(cancel.error, NETWORK_PROBLEM)}</InlineError>}
        <Button
          variant="secondary"
          wide
          disabled={cancel.isPending}
          onClick={() =>
            cancel.mutate(
              { offerId: shift.offer_id! },
              {
                onSuccess: () => {
                  refresh()
                  onClose()
                },
              },
            )
          }
        >
          Zostaję na tej zmianie
        </Button>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <p className="m-0">
        Osoby, które mogą wziąć tę zmianę (także z innych lokali firmy), dostaną powiadomienie. Gdy ktoś powie „Biorę”,
        kierownik zdecyduje.
      </p>
      <p className="m-0 font-semibold">Do decyzji kierownika to nadal Twoja zmiana.</p>
      {offer.isError && <InlineError>{errorMessage(offer.error, NETWORK_PROBLEM)}</InlineError>}
      <Button
        wide
        disabled={offer.isPending}
        onClick={() =>
          offer.mutate(
            { assignmentId: shift.id },
            {
              onSuccess: (response) => {
                setSent((response.data as OfferMadeOut).notified)
                refresh()
              },
            },
          )
        }
      >
        Oddaj zmianę
      </Button>
    </div>
  )
}
