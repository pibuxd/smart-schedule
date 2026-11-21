import { useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";

import type { HoursProposalOut, MyRequestOut } from "../../api/generated/model";
import { useReportMyHours } from "../../api/generated/worktime/worktime";
import { Button } from "../../components/ui/button";
import { InlineError } from "../../components/ui/status";
import { errorMessage, NETWORK_PROBLEM } from "../../lib/api-error";
import { dayTitle, parseDate, shortTime } from "../../lib/dates";
import { differenceText } from "../schedule/hours";

const SENT: Record<NonNullable<HoursProposalOut["sent_status"]>, string> = {
  pending: "Wysłane. Czeka na kierownika.",
  approved: "Kierownik zatwierdził te godziny.",
  rejected: "Kierownik odrzucił te godziny.",
  cancelled: "Zgłoszenie wycofane.",
  replaced: "Zastąpione innymi godzinami.",
  expired: "Nie masz już tej zmiany w grafiku, więc te godziny się nie liczą.",
};

/**
 * Reports of other hours the assistant prepared from one message (overtime, leaving early). Nothing goes to the
 * manager by itself: "Wyślij kierownikowi" sends one, as the same report from "Mój grafik".
 */
export function HoursProposals({ request }: { request: MyRequestOut }) {
  const proposals = request.hours_reports ?? [];
  if (proposals.length === 0) return null;
  return (
    <ul className="m-0 grid list-none gap-2 p-0" aria-label="Zgłoszenia innych godzin">
      {proposals.map((proposal) => (
        <Proposal
          key={`${proposal.date}:${proposal.start_time}:${proposal.end_time}`}
          proposal={proposal}
          requestId={request.id}
        />
      ))}
    </ul>
  );
}

function Proposal({
  proposal,
  requestId,
}: {
  proposal: HoursProposalOut;
  requestId: string;
}) {
  const send = useReportMyHours();
  const queryClient = useQueryClient();
  const status = proposal.sent_status;
  return (
    <li className="grid gap-2 rounded-md border border-line bg-surface p-3">
      <span className="flex items-center gap-1.5 text-sm font-semibold text-ink-muted">
        <Clock size={16} aria-hidden="true" /> Inne godziny zmiany
      </span>
      <p className="m-0">
        <span className="font-semibold">
          {dayTitle(parseDate(proposal.date))}:{" "}
          {shortTime(proposal.start_time)}–{shortTime(proposal.end_time)}
        </span>{" "}
        zamiast {shortTime(proposal.planned_start_time)}–
        {shortTime(proposal.planned_end_time)} (
        {differenceText(proposal.difference_minutes)})
      </p>
      <p className="m-0 text-sm text-ink-muted">
        {proposal.position_name}, {proposal.location_name}
        {proposal.reason && `. Powód: ${proposal.reason}`}
      </p>
      {status ? (
        <p
          role="status"
          className={
            "m-0 text-sm font-semibold " +
            (status === "approved" ? "text-prefer" : "text-ink-muted")
          }
        >
          {SENT[status]}
        </p>
      ) : proposal.assignment_id === null ? (
        <p className="m-0 text-sm text-ink-muted">
          Grafik się zmienił i nie masz już tej zmiany, więc tego zgłoszenia nie
          wyślesz.
        </p>
      ) : (
        <div>
          <Button
            size="normal"
            disabled={send.isPending}
            onClick={() =>
              send.mutate(
                {
                  data: {
                    assignment_id: proposal.assignment_id!,
                    start_time: proposal.start_time,
                    end_time: proposal.end_time,
                    reason: proposal.reason,
                    request_id: requestId,
                  },
                },
                { onSuccess: () => void queryClient.invalidateQueries() },
              )
            }
          >
            {send.isPending ? "Wysyłam…" : "Wyślij kierownikowi"}
          </Button>
        </div>
      )}
      {send.isError && (
        <InlineError>{errorMessage(send.error, NETWORK_PROBLEM)}</InlineError>
      )}
    </li>
  );
}
