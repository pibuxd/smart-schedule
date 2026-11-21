import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import type { MyShiftOut } from '../../api/generated/model'
import { useCancelMyHoursChange, useReportMyHours } from '../../api/generated/worktime/worktime'
import { Button } from '../../components/ui/button'
import { TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayTitle, parseDate, shortTime } from '../../lib/dates'
import { clockTime, differenceSentence, differenceText, isTime, minutesBetween } from './hours'

const REASON_MAX = 300

/**
 * "Zgłoś inne godziny": the hours I really work (worked) on one of my published shifts, longer (overtime) or shorter
 * (I feel ill and leave early). The manager approves or rejects it; until then the schedule's hours count.
 */
export function HoursSheet({ shift, now, onClose }: { shift: MyShiftOut | null; now: Date; onClose: () => void }) {
  return (
    <Sheet
      open={shift !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Inne godziny tej zmiany"
      description={
        shift
          ? `${dayTitle(parseDate(shift.date))}, w grafiku ${shortTime(shift.start_time)}–${shortTime(shift.end_time)}, ${shift.position_name}`
          : undefined
      }
    >
      {shift && <ReportHours key={shift.id} shift={shift} now={now} onClose={onClose} />}
    </Sheet>
  )
}

function ReportHours({ shift, now, onClose }: { shift: MyShiftOut; now: Date; onClose: () => void }) {
  const counted = shift.worked ?? shift
  const [start, setStart] = useState(counted.start_time)
  const [end, setEnd] = useState(counted.end_time)
  const [reason, setReason] = useState('')
  const [sent, setSent] = useState(false)
  const send = useReportMyHours()
  const cancel = useCancelMyHoursChange()
  const queryClient = useQueryClient()
  const refresh = () => void queryClient.invalidateQueries()

  if (sent) {
    return (
      <div className="grid gap-4">
        <p role="status" className="m-0">
          Wysłane. Kierownik zatwierdzi albo odrzuci te godziny, a Ty dostaniesz powiadomienie. Do tego czasu liczą się
          godziny z grafiku.
        </p>
        <Button wide onClick={onClose}>
          Gotowe
        </Button>
      </div>
    )
  }

  const running = Date.parse(counted.start_at) <= now.getTime() && now.getTime() < Date.parse(counted.end_at)
  const valid = isTime(start) && isTime(end)
  const planned = minutesBetween(shift.start_time, shift.end_time)
  const difference = valid ? minutesBetween(start, end) - planned : 0
  const same = valid && start === counted.start_time && end === counted.end_time
  const waiting = shift.report
  const alreadyWaiting = valid && waiting != null && start === waiting.start_time && end === waiting.end_time
  const busy = send.isPending || cancel.isPending

  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (!valid || same || alreadyWaiting) return
        send.mutate(
          { data: { assignment_id: shift.id, start_time: start, end_time: end, reason: reason.trim() } },
          {
            onSuccess: () => {
              setSent(true)
              refresh()
            },
          },
        )
      }}
    >
      {shift.worked && (
        <p className="m-0">
          Liczą się {shortTime(shift.worked.start_time)}–{shortTime(shift.worked.end_time)} (
          {shift.worked.by_manager ? 'od kierownika' : 'zatwierdzone'}).
        </p>
      )}
      {waiting && (
        <div className="grid gap-2 rounded-md bg-paper p-3">
          <p className="m-0">
            Czeka na kierownika: {shortTime(waiting.start_time)}–{shortTime(waiting.end_time)} (
            {differenceText(waiting.difference_minutes)}). Nowe godziny zastąpią to zgłoszenie.
          </p>
          <div>
            <Button
              type="button"
              variant="secondary"
              size="normal"
              disabled={busy}
              onClick={() => cancel.mutate({ changeId: waiting.id }, { onSuccess: () => { refresh(); onClose() } })}
            >
              Wycofaj zgłoszenie
            </Button>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <TextField label="Od" type="time" required value={start} onChange={(event) => setStart(event.target.value)} />
        <TextField label="Do" type="time" required value={end} onChange={(event) => setEnd(event.target.value)} />
      </div>
      {running && (
        <div>
          <Button
            type="button"
            variant="secondary"
            size="normal"
            // The clock at the click: the screen's `now` only moves at the edges of shifts.
            onClick={() => setEnd(clockTime(new Date(), counted.start_at))}
          >
            Wychodzę teraz
          </Button>
        </div>
      )}
      <TextField
        label="Powód (nie musisz pisać)"
        value={reason}
        maxLength={REASON_MAX}
        placeholder="np. źle się czuję, dostawa"
        onChange={(event) => setReason(event.target.value)}
      />
      <p role="status" className="m-0 font-semibold">
        {!valid
          ? 'Wpisz godziny od i do.'
          : same
            ? 'To te same godziny, które liczą się teraz.'
            : alreadyWaiting
              ? 'Takie zgłoszenie już czeka na kierownika.'
              : differenceSentence(difference)}
      </p>
      {send.isError && <InlineError>{errorMessage(send.error, NETWORK_PROBLEM)}</InlineError>}
      {cancel.isError && <InlineError>{errorMessage(cancel.error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={busy || !valid || same || alreadyWaiting}>
        {send.isPending ? 'Wysyłam…' : 'Wyślij kierownikowi'}
      </Button>
    </form>
  )
}
