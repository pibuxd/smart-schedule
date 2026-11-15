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
 * approves someone. While it is being given away, "Jednak nie oddaję" takes the offer back.
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
  const [sent, setSent] = useState<OfferMadeOut | null>(null)
  const refresh = () => void queryClient.invalidateQueries()

  if (sent !== null) {
    return (
      <div className="grid gap-4">
        <p role="status" className="m-0">
          {sent.notified > 0
            ? `${toldText(sent.notified, sent.notified_here ?? 0)} Gdy ktoś się zgłosi, dostaniesz powiadomienie. Potem zdecyduje kierownik.`
            : 'Teraz nikt nie może wziąć tej zmiany: inni pracują, zaznaczyli „nie mogę” albo mają inne stanowisko. Zmiana czeka w „Zmiany do wzięcia”. Najlepiej porozmawiaj też z kierownikiem.'}
        </p>
        <p className="m-0 font-semibold">Dopóki kierownik nie zdecyduje, to nadal Twoja zmiana.</p>
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
            ? 'Ktoś chce wziąć tę zmianę. Teraz decyduje kierownik.'
            : 'Jeszcze nikt się nie zgłosił.'}
        </p>
        <p className="m-0 font-semibold">Dopóki kierownik nie zdecyduje, to nadal Twoja zmiana. Jeśli nic się nie zmieni, przyjdź do pracy.</p>
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
          Jednak nie oddaję
        </Button>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <p className="m-0">
        Damy znać osobom, które mogą wziąć tę zmianę (także z innych lokali firmy). Gdy ktoś się zgłosi, kierownik
        zdecyduje.
      </p>
      <p className="m-0 font-semibold">Dopóki kierownik nie zdecyduje, to nadal Twoja zmiana.</p>
      {offer.isError && <InlineError>{errorMessage(offer.error, NETWORK_PROBLEM)}</InlineError>}
      <Button
        wide
        disabled={offer.isPending}
        onClick={() =>
          offer.mutate(
            { assignmentId: shift.id },
            {
              onSuccess: (response) => {
                setSent(response.data as OfferMadeOut)
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

function dative(count: number): string {
  return count === 1 ? '1 osobie' : `${count} osobom`
}

/** "Daliśmy znać 38 osobom: 2 z Twojego lokalu i 36 z innych lokali firmy." */
function toldText(all: number, here: number): string {
  const elsewhere = all - here
  if (elsewhere === 0) return `Daliśmy znać ${dative(all)} z Twojego lokalu, które mogą wziąć tę zmianę.`
  if (here === 0) return `Daliśmy znać ${dative(all)} z innych lokali firmy. Z Twojego lokalu nikt nie może teraz jej wziąć.`
  return `Daliśmy znać ${dative(all)}: ${here} z Twojego lokalu i ${elsewhere} z innych lokali firmy.`
}
