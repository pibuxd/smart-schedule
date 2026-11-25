import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  getMyRequestsQueryKey,
  useCreateMyRequest,
  useDeleteMyRequest,
  useEndMyRequest,
  useMyRequests,
  useSaveMyCalendar,
  useUpdateMyRequest,
} from "../../api/generated/availability/availability";
import type { CannotMarkOut, MyRequestOut } from "../../api/generated/model";
import {
  ChatComposer,
  ChatMessage,
  ChatTyping,
} from "../../components/assistant/Chat";
import { Button } from "../../components/ui/button";
import { Disclosure } from "../../components/ui/disclosure";
import { InlineError } from "../../components/ui/status";
import { errorMessage, NETWORK_PROBLEM } from "../../lib/api-error";
import { periodWords, shortTime, sinceWords } from "../../lib/dates";
import { useEmployeeChat, useScreenChatScope } from "./employee-chat";
import { HoursProposals } from "./HoursProposals";

/** Requests that count: understood by the assistant (they reach the generator) or left for the manager. */
const isSaved = (request: MyRequestOut) =>
  request.status === "interpreted" || request.status === "needs_manager";

// How long a fresh request is shown as "being read" before we stop asking the server.
const READING_MS = 60_000;

/** A lasting request written for an earlier month: it counts here too, but belongs to that month's chat. */
const isCarried = (request: MyRequestOut) => Boolean(request.carried_from);

/** "14.12" for "2026-12-14". */
const shortDate = (iso: string) =>
  `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;

/** "9:00–11:00", "od 10:00", "do 11:00"; "" for the whole day. */
function markHours(mark: CannotMarkOut): string {
  const from = mark.from_time ? shortTime(mark.from_time) : null;
  const to = mark.to_time ? shortTime(mark.to_time) : null;
  if (from && to) return `${from}–${to}`;
  if (from) return `od ${from}`;
  return to ? `do ${to}` : "";
}

/**
 * Days the request says the person cannot work that the calendar does not show so. With hours ("we wtorki nie mogę
 * od 9 do 11") the button marks "nie mogę" only in those hours, so the rest of the day stays open to work; days the
 * calendar blocks for the whole day can be narrowed to them.
 */
function CannotMark({
  mark,
  disabled,
  marking,
  onMark,
}: {
  mark: CannotMarkOut;
  disabled: boolean;
  marking: boolean;
  onMark: () => void;
}) {
  const hours = markHours(mark);
  const days = mark.days.map(shortDate).join(", ");
  const text = mark.whole_day
    ? `W kalendarzu te dni mają „Nie mogę” przez cały dzień, a prośba mówi tylko o godzinach ${hours}: ${days}.`
    : hours
      ? `W kalendarzu te dni są nadal do pracy w godzinach ${hours}: ${days}.`
      : `W kalendarzu te dni są nadal do pracy: ${days}.`;
  const label = mark.whole_day
    ? `Zmień na „nie mogę” ${hours}`
    : hours
      ? `Zaznacz „nie mogę” ${hours}`
      : "Zaznacz „nie mogę”";
  return (
    <div className="grid gap-2 rounded-md border border-line p-3">
      <p className="m-0 text-sm">{text}</p>
      {hours && (
        <p className="m-0 text-sm text-ink-muted">
          W pozostałych godzinach tych dni możesz pracować.
        </p>
      )}
      <div>
        <Button
          variant="secondary"
          size="normal"
          disabled={disabled || marking}
          onClick={onMark}
        >
          {marking ? "Zapisuję…" : label}
        </Button>
      </div>
    </div>
  );
}

/** The assistant's own words to the person: an answer, or a word about the request. */
function Reply({ request }: { request: MyRequestOut }) {
  return request.reply ? (
    <p className="m-0 whitespace-pre-wrap">{request.reply}</p>
  ) : null;
}

/**
 * The assistant's question back: it was not sure what the person meant and saves nothing until they answer.
 * `waiting`: it is about the newest message, so the next one answers it.
 */
function Question({
  question,
  waiting,
}: {
  question: string;
  waiting: boolean;
}) {
  return (
    <div className="grid gap-1">
      <p className="m-0 font-semibold whitespace-pre-wrap">{question}</p>
      {waiting && (
        <p className="m-0 text-sm text-ink-muted">
          Odpowiedz niżej. Do tego czasu niczego nie zapisuję.
        </p>
      )}
    </div>
  );
}

/** Notes from the app: the calendar says the opposite, or the shift is not on the person's position. */
function Notes({ notes }: { notes: string[] }) {
  return notes.length > 0 ? (
    <ul className="m-0 grid list-none gap-1 rounded-md bg-prefer-not-soft p-3 text-sm text-prefer-not">
      {notes.map((note, i) => (
        <li key={i}>{note}</li>
      ))}
    </ul>
  ) : null;
}

/**
 * "Tylko w grudniu" / "Na stałe": how long a saved request counts. "Na stałe" carries it over to every later month
 * until the person (or the manager) ends it there.
 */
function LastingChoice({
  lasting,
  only,
  disabled,
  onChange,
}: {
  lasting: boolean;
  /** "w grudniu", or the days of the period ("1–7 grudnia"). */
  only: string;
  disabled: boolean;
  onChange: (lasting: boolean) => void;
}) {
  const options = [
    { value: false, label: `Tylko ${only}` },
    { value: true, label: "Na stałe" },
  ];
  return (
    <fieldset
      className="m-0 flex flex-wrap gap-1 border-0 p-0"
      disabled={disabled}
    >
      <legend className="sr-only">Jak długo obowiązuje prośba</legend>
      {options.map((option) => (
        <button
          key={option.label}
          type="button"
          aria-pressed={lasting === option.value}
          onClick={() => lasting !== option.value && onChange(option.value)}
          className={
            "min-h-(--touch) cursor-pointer rounded-sm border-2 px-3 text-sm font-semibold " +
            (lasting === option.value
              ? "border-accent bg-accent text-accent-ink"
              : "border-line bg-surface text-ink hover:border-accent")
          }
        >
          {option.label}
        </button>
      ))}
    </fieldset>
  );
}

/**
 * "Nie o to mi chodziło": first a way to write the request again (the assistant reads it anew), and only as a
 * second choice handing it to the manager as written.
 */
function WrongChoice({
  request,
  busy,
  onRewrite,
  onToManager,
}: {
  request: MyRequestOut;
  busy: boolean;
  onRewrite: (text: string) => void;
  onToManager: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(request.text);
  if (!open)
    return (
      <div>
        <Button
          variant="quiet"
          size="normal"
          disabled={busy}
          onClick={() => setOpen(true)}
        >
          Nie o to mi chodziło
        </Button>
      </div>
    );
  return (
    <form
      className="grid gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (text.trim() && text.trim() !== request.text) onRewrite(text.trim());
      }}
    >
      <label className="grid gap-1 text-sm">
        Napisz to inaczej
        <textarea
          className="rounded-md border-2 border-ink p-2 text-base"
          maxLength={1000}
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          type="submit"
          size="normal"
          disabled={busy || !text.trim() || text.trim() === request.text}
        >
          Wyślij poprawioną
        </Button>
        <Button
          type="button"
          variant="quiet"
          size="normal"
          disabled={busy}
          onClick={onToManager}
        >
          Niech przeczyta kierownik
        </Button>
        <Button
          type="button"
          variant="quiet"
          size="normal"
          disabled={busy}
          onClick={() => setOpen(false)}
        >
          Anuluj
        </Button>
      </div>
    </form>
  );
}

/** How the request was understood, in plain words, with a way to say "that is not what I meant". */
function RequestStatus({
  request,
  editable,
  waiting = false,
  busy,
  marking,
  only,
  onRewrite,
  onToManager,
  onMarkCannot,
  onLasting,
}: {
  request: MyRequestOut;
  editable: boolean;
  /** The newest message of the chat: an open question waits for the next one. */
  waiting?: boolean;
  busy: boolean;
  marking: boolean;
  /** "w grudniu": the month (or days of the period) of this chat, for "Tylko w grudniu". */
  only: string;
  onRewrite: (text: string) => void;
  onToManager: () => void;
  onMarkCannot: (mark: CannotMarkOut) => void;
  onLasting: (lasting: boolean) => void;
}) {
  if (request.status === "rejected")
    return (
      <div className="grid gap-2">
        <p className="m-0 text-sm text-ink-muted">
          {request.summary ?? "Ta prośba została odrzucona."}
        </p>
        {editable && (
          <div>
            <Button
              variant="quiet"
              size="normal"
              disabled={busy}
              onClick={onToManager}
            >
              Przekaż kierownikowi
            </Button>
          </div>
        )}
      </div>
    );
  if (request.status === "superseded") {
    return (
      <p className="m-0 text-sm text-ink-muted">
        Ta prośba została zastąpiona nowszą. Nie wpływa już na układanie
        grafiku.
      </p>
    );
  }
  if (
    request.status === "answered" &&
    (request.reply || request.summary || request.question)
  ) {
    return (
      <div className="grid gap-2">
        {request.reply ? (
          <Reply request={request} />
        ) : (
          request.summary && <p className="m-0">{request.summary}</p>
        )}
        {request.question && (
          <Question question={request.question} waiting={waiting} />
        )}
        {editable && (
          <div>
            <Button
              variant="quiet"
              size="normal"
              disabled={busy}
              onClick={onToManager}
            >
              Niech przeczyta kierownik
            </Button>
          </div>
        )}
      </div>
    );
  }
  if (request.status === "interpreted" && request.summary) {
    const marks = request.cannot_marks ?? [];
    return (
      <div className="grid gap-2">
        <Reply request={request} />
        <p className="m-0">
          <span className="font-semibold">Tak to zrozumieliśmy: </span>
          {request.summary}
        </p>
        <p className="m-0 text-sm text-ink-muted">
          {request.lasting
            ? "Generator grafiku spróbuje to spełnić, także w kolejnych miesiącach. Kalendarz się nie zmienia."
            : "Generator grafiku spróbuje to spełnić. Kalendarz się nie zmienia."}
        </p>
        {editable && request.can_last && (
          <LastingChoice
            lasting={Boolean(request.lasting)}
            only={only}
            disabled={busy}
            onChange={onLasting}
          />
        )}
        <Notes notes={request.notes} />
        {editable &&
          marks.map((mark) => (
            <CannotMark
              key={`${mark.from_time}-${mark.to_time}-${mark.whole_day}`}
              mark={mark}
              disabled={busy}
              marking={marking}
              onMark={() => onMarkCannot(mark)}
            />
          ))}
        {editable && (
          <WrongChoice
            request={request}
            busy={busy}
            onRewrite={onRewrite}
            onToManager={onToManager}
          />
        )}
      </div>
    );
  }
  if (request.status === "new")
    return <ChatTyping />;
  return (
    <div className="grid gap-2">
      <Reply request={request} />
      <p className="m-0 text-sm text-ink-muted">
        Kierownik przeczyta tę prośbę sam. Generator nie użyje jej
        automatycznie.
      </p>
    </div>
  );
}

/** One conversation of a person: a period (`periodId`) or, before the manager asks for one, a month (`month`). */
type Scope = { companyId: string; periodId?: string; month?: string };

/** The person's messages of one conversation; asks again while the assistant is still reading a fresh one. */
function useRequests({ companyId, periodId, month }: Scope) {
  const params = periodId
    ? { company_id: companyId, period_id: periodId }
    : { company_id: companyId, month };
  const requests = useMyRequests(params, {
    query: {
      // A fresh request is read by the assistant within seconds; look again until it is.
      refetchInterval: (query) => {
        const rows =
          (query.state.data?.data as MyRequestOut[] | undefined) ?? [];
        return rows.some(
          (r) =>
            r.status === "new" &&
            Date.now() - Date.parse(r.created_at) < READING_MS,
        )
          ? 2000
          : false;
      },
    },
  });
  const queryClient = useQueryClient();
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getMyRequestsQueryKey(params) });
  const list = (requests.data?.data as MyRequestOut[] | undefined) ?? [];
  return { requests, list, params, refresh };
}

/** Writing a request again: the assistant reads the new text from the start. */
function EditForm({
  request,
  text,
  busy,
  assistantReads,
  onChange,
  onCancel,
  onSave,
}: {
  request: MyRequestOut;
  text: string;
  busy: boolean;
  assistantReads: boolean;
  onChange: (text: string) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div className="py-2 pr-2">
      <form
        className="grid gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          onSave();
        }}
      >
        <label className="grid gap-1">
          Treść prośby
          <textarea
            className="rounded-md border-2 border-ink p-2"
            maxLength={1000}
            rows={3}
            value={text}
            onChange={(e) => onChange(e.target.value)}
          />
        </label>
        <p className="m-0 text-sm text-ink-muted">
          {request.waiting
            ? "Napisz całą prośbę razem z odpowiedzią na pytanie."
            : "Kierownik zobaczy poprawioną treść. Jego wcześniejsza decyzja i nadana prośbie ważność pozostaną w mocy."}{" "}
          {assistantReads &&
            "Po zmianie tekstu zewnętrzny asystent AI przeczyta prośbę ponownie."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            disabled={busy || !text.trim() || text.trim() === request.text}
          >
            Zapisz prośbę
          </Button>
          <Button
            type="button"
            variant="quiet"
            disabled={busy}
            onClick={onCancel}
          >
            Anuluj
          </Button>
        </div>
      </form>
    </div>
  );
}

/** The bin, and a second tap to be sure. */
function RemoveControl({
  asking,
  busy,
  onAsk,
  onCancel,
  onRemove,
}: {
  asking: boolean;
  busy: boolean;
  onAsk: () => void;
  onCancel: () => void;
  onRemove: () => void;
}) {
  return asking ? (
    <span className="flex flex-wrap items-center justify-end gap-1">
      <span className="text-sm font-semibold">Usunąć tę prośbę?</span>
      <Button variant="quiet" size="normal" disabled={busy} onClick={onRemove}>
        Tak, usuń
      </Button>
      <Button variant="quiet" size="normal" onClick={onCancel}>
        Nie
      </Button>
    </span>
  ) : (
    <Button
      variant="quiet"
      size="normal"
      aria-label="Usuń prośbę"
      title="Usuń prośbę"
      className="min-w-(--touch) px-2"
      onClick={onAsk}
    >
      <Trash2 size={18} aria-hidden="true" />
    </Button>
  );
}

/** "Zakończ" for a lasting request from an earlier month, and a second tap to be sure. */
function EndControl({
  since,
  asking,
  busy,
  onAsk,
  onCancel,
  onEnd,
}: {
  /** "od stycznia": the month on screen, from which it stops counting. */
  since: string;
  asking: boolean;
  busy: boolean;
  onAsk: () => void;
  onCancel: () => void;
  onEnd: () => void;
}) {
  return asking ? (
    <span className="flex flex-wrap items-center gap-1">
      <span className="text-sm font-semibold">Zakończyć {since}?</span>
      <Button variant="quiet" size="normal" disabled={busy} onClick={onEnd}>
        Tak, zakończ
      </Button>
      <Button variant="quiet" size="normal" onClick={onCancel}>
        Nie
      </Button>
    </span>
  ) : (
    <Button variant="quiet" size="normal" onClick={onAsk}>
      Zakończ
    </Button>
  );
}

/**
 * "Twoje prośby" under the calendar: only the requests that count (understood by the assistant, or left for the
 * manager to read); each can be corrected or removed here. The conversation itself is in the chat that slides in
 * from the right (`EmployeeChatProvider`); while this window is on screen, the "Asystent" button opens it on this
 * window's month too. A request belongs to the period the manager asked for (`periodId`), or, before that, to the
 * month on the screen (`month`, its first day): the manager sees it in every period that covers that month.
 * Lasting requests from earlier months are listed too ("Na stałe od grudnia"), with "Zakończ" instead of editing.
 */
function RequestsWindow({
  companyId,
  periodId,
  month,
  span,
  editable,
  assistantReads = false,
}: {
  companyId: string;
  periodId?: string;
  month?: string;
  /** The first and last day of the period (month) on screen. */
  span?: { start: string; end: string };
  editable: boolean;
  assistantReads?: boolean;
}) {
  const chat = useEmployeeChat();
  useScreenChatScope({ periodId, month, editable });
  const { requests, list, refresh } = useRequests({
    companyId,
    periodId,
    month,
  });
  const remove = useDeleteMyRequest({ mutation: { onSuccess: refresh } });
  const [removing, setRemoving] = useState<string | null>(null);
  const update = useUpdateMyRequest({ mutation: { onSuccess: refresh } });
  const finish = useEndMyRequest({ mutation: { onSuccess: refresh } });
  const [ending, setEnding] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(
    null,
  );
  const chatOpen = chat?.open ?? false;
  const openChat = () => chat?.openChat({ periodId, month, editable });
  const own = list.filter((r) => !isCarried(r));
  const saved = own.filter(isSaved);
  const carried = list.filter(isCarried);
  const only = span ? periodWords(span.start, span.end) : "ten okres";
  const since = span ? sinceWords(span.start) : "od tego okresu";
  // Messages the assistant asked about and nobody answered: listed apart, so a request is never lost quietly.
  const waiting = editable ? own.filter((r) => r.waiting) : [];
  const reading = assistantReads && own.some((r) => r.status === "new");
  // The newest message left a trace only in the chat: say so in the window, so it does not look lost.
  const last = own.at(-1);
  const notSaved =
    last &&
    !waiting.includes(last) &&
    (last.status === "rejected" || last.status === "answered")
      ? last
      : undefined;
  const failure = update.error ?? remove.error ?? finish.error;
  const endRequest = (request: MyRequestOut, ended: boolean) =>
    finish.mutate(
      {
        requestId: request.id,
        data: periodId
          ? { company_id: companyId, period_id: periodId, ended }
          : { company_id: companyId, month, ended },
      },
      { onSettled: () => setEnding(null) },
    );

  return (
    <section
      aria-labelledby="requests-title"
      className="grid gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="requests-title" className="m-0 text-lg font-semibold">
          Twoje prośby
        </h2>
        {chat && (editable || list.length > 0) && (
          <Button variant="secondary" size="normal" onClick={openChat}>
            <MessageCircle size={18} aria-hidden="true" />
            {!editable
              ? "Pokaż rozmowę"
              : assistantReads
                ? "Napisz do asystenta"
                : "Napisz prośbę"}
          </Button>
        )}
      </div>
      {requests.isPending && (
        <p role="status" className="m-0 text-sm text-ink-muted">
          Wczytuję prośby…
        </p>
      )}
      {requests.isError && (
        <InlineError>
          Nie udało się wczytać Twoich próśb.{" "}
          <button
            className="min-h-(--touch) cursor-pointer underline"
            onClick={() => void requests.refetch()}
          >
            Spróbuj ponownie
          </button>
        </InlineError>
      )}
      {waiting.length > 0 && (
        <ul
          className="m-0 grid list-none gap-2 p-0"
          aria-label="Czekają na Twoją odpowiedź"
        >
          {waiting.map((request) => (
            <li
              key={request.id}
              className="rounded-md border border-dashed border-line py-1 pr-1 pl-3"
            >
              {editing?.id === request.id ? (
                <EditForm
                  request={request}
                  text={editing.text}
                  busy={update.isPending}
                  assistantReads={assistantReads}
                  onChange={(text) => setEditing({ id: request.id, text })}
                  onCancel={() => setEditing(null)}
                  onSave={() =>
                    update.mutate(
                      {
                        requestId: request.id,
                        data: { text: editing.text.trim() },
                      },
                      { onSuccess: () => setEditing(null) },
                    )
                  }
                />
              ) : (
                <div className="grid gap-2 py-2 pr-2">
                  {/* A second or third question: the earlier messages of the same request come first. */}
                  {(request.exchange ?? []).map((earlier, i) => (
                    <span
                      key={i}
                      className="text-sm text-ink-muted [overflow-wrap:anywhere]"
                    >
                      {earlier.text}
                    </span>
                  ))}
                  <span className="[overflow-wrap:anywhere]">
                    {request.text}
                  </span>
                  <span className="text-sm text-ink-muted">
                    Nie jest zapisana. Asystent pyta: {request.question}
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {request.can_answer ? (
                      <Button
                        variant="secondary"
                        size="normal"
                        onClick={openChat}
                      >
                        Odpowiedz
                      </Button>
                    ) : (
                      <Button
                        variant="secondary"
                        size="normal"
                        onClick={() =>
                          setEditing({ id: request.id, text: request.text })
                        }
                      >
                        Napisz ją od nowa
                      </Button>
                    )}
                    <Button
                      variant="quiet"
                      size="normal"
                      disabled={update.isPending}
                      onClick={() =>
                        update.mutate({
                          requestId: request.id,
                          data: { understood: false },
                        })
                      }
                    >
                      Niech przeczyta kierownik
                    </Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {!requests.isPending &&
        !requests.isError &&
        saved.length === 0 &&
        carried.length === 0 &&
        waiting.length === 0 && (
          <p className="m-0 text-sm text-ink-muted">
            {editable
              ? "Nie masz jeszcze próśb. Napisz, czego kalendarz nie powie, na przykład: „W piątki wolę pracować rano”."
              : "Nie masz próśb na ten okres."}
          </p>
        )}
      {saved.length > 0 && (
        <ul
          className="m-0 grid list-none gap-2 p-0"
          aria-label="Zapisane prośby"
        >
          {saved.map((request) => (
            <li
              key={request.id}
              className="rounded-md border border-grid py-1 pr-1 pl-3"
            >
              {editable && editing?.id === request.id ? (
                <EditForm
                  request={request}
                  text={editing.text}
                  busy={update.isPending}
                  assistantReads={assistantReads}
                  onChange={(text) => setEditing({ id: request.id, text })}
                  onCancel={() => setEditing(null)}
                  onSave={() =>
                    update.mutate(
                      {
                        requestId: request.id,
                        data: { text: editing.text.trim() },
                      },
                      { onSuccess: () => setEditing(null) },
                    )
                  }
                />
              ) : (
                <div className="flex flex-wrap items-center gap-x-2">
                  <span className="min-w-0 flex-1 basis-48 py-2">
                    <span className="block [overflow-wrap:anywhere]">
                      {request.text}
                    </span>
                    <span className="block text-sm text-ink-muted">
                      {request.status === "interpreted" && request.summary ? (
                        <>
                          Asystent zrozumiał: <span>{request.summary}</span>
                        </>
                      ) : request.status === "interpreted" ? (
                        "Zostanie uwzględniona przy układaniu grafiku."
                      ) : (
                        "Kierownik przeczyta ją sam."
                      )}
                      {!editable && request.lasting && " Na stałe."}
                      {request.ends_from &&
                        ` Nie obowiązuje ${sinceWords(request.ends_from)}.`}
                    </span>
                    {editable && request.can_last && (
                      <span className="mt-1 block">
                        <LastingChoice
                          lasting={Boolean(request.lasting)}
                          only={only}
                          disabled={update.isPending}
                          onChange={(lasting) =>
                            update.mutate({
                              requestId: request.id,
                              data: { lasting },
                            })
                          }
                        />
                      </span>
                    )}
                  </span>
                  {editable && (
                    <span className="ml-auto flex shrink-0 items-center">
                      {removing !== request.id && (
                        <Button
                          variant="quiet"
                          size="normal"
                          aria-label="Edytuj prośbę"
                          title="Edytuj prośbę"
                          className="min-w-(--touch) px-2"
                          onClick={() =>
                            setEditing({ id: request.id, text: request.text })
                          }
                        >
                          <Pencil size={18} aria-hidden="true" />
                        </Button>
                      )}
                      <RemoveControl
                        asking={removing === request.id}
                        busy={remove.isPending}
                        onAsk={() => setRemoving(request.id)}
                        onCancel={() => setRemoving(null)}
                        onRemove={() =>
                          remove.mutate(
                            { requestId: request.id },
                            { onSettled: () => setRemoving(null) },
                          )
                        }
                      />
                    </span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {carried.length > 0 && (
        <ul
          className="m-0 grid list-none gap-2 p-0"
          aria-label="Prośby na stałe z wcześniejszych miesięcy"
        >
          {carried.map((request) => (
            <li
              key={request.id}
              className={
                request.ended
                  ? "rounded-md border border-dashed border-line py-1 pr-1 pl-3"
                  : "rounded-md border border-grid py-1 pr-1 pl-3"
              }
            >
              <div className="flex flex-wrap items-center gap-x-2">
                <span className="min-w-0 flex-1 basis-48 py-2">
                  <span
                    className={
                      request.ended
                        ? "block text-ink-muted [overflow-wrap:anywhere]"
                        : "block [overflow-wrap:anywhere]"
                    }
                  >
                    {request.text}
                  </span>
                  <span className="block text-sm text-ink-muted">
                    {request.ended
                      ? `Zakończona: nie obowiązuje ${since}.${request.ended_by === "manager" ? " Zakończył ją kierownik." : ""}`
                      : `Na stałe ${sinceWords(request.carried_from!)}.${request.summary ? ` Asystent zrozumiał: ${request.summary}` : " Kierownik przeczyta ją sam."}`}
                  </span>
                </span>
                {editable && !request.ended && (
                  <span
                    className={
                      // The question and its two answers need the whole width of a phone.
                      ending === request.id
                        ? "flex basis-full items-center pb-1"
                        : "ml-auto flex shrink-0 items-center"
                    }
                  >
                    <EndControl
                      since={since}
                      asking={ending === request.id}
                      busy={finish.isPending}
                      onAsk={() => setEnding(request.id)}
                      onCancel={() => setEnding(null)}
                      onEnd={() => endRequest(request, true)}
                    />
                  </span>
                )}
                {editable &&
                  request.ended &&
                  request.ended_by === "employee" && (
                    <span className="ml-auto flex shrink-0 items-center">
                      <Button
                        variant="quiet"
                        size="normal"
                        disabled={finish.isPending}
                        onClick={() => endRequest(request, false)}
                      >
                        Przywróć
                      </Button>
                    </span>
                  )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {reading && <ChatTyping>Asystent myśli…</ChatTyping>}
      {notSaved && !chatOpen && (
        <p className="m-0 text-sm text-ink-muted">
          {notSaved.status === "rejected"
            ? "Twoja ostatnia wiadomość została odrzucona i nie jest prośbą."
            : "Asystent odpowiedział na Twoją ostatnią wiadomość."}{" "}
          <button
            type="button"
            className="min-h-(--touch) cursor-pointer font-semibold text-accent underline"
            onClick={openChat}
          >
            Pokaż odpowiedź
          </button>
        </p>
      )}
      {failure && !chatOpen && (
        <InlineError>{errorMessage(failure, NETWORK_PROBLEM)}</InlineError>
      )}
    </section>
  );
}

/**
 * The conversation, in the chat that slides in from the right (`EmployeeChatProvider`): every message with the
 * assistant's answer, and the field to write. When the assistant is on (`assistantReads`), the text also goes to
 * an outside AI service, and the chat says so.
 */
export function RequestsChat({
  companyId,
  periodId,
  month,
  editable,
  assistantReads = false,
  only = "ten okres",
  text,
  onTextChange,
}: {
  companyId: string;
  periodId?: string;
  month?: string;
  editable: boolean;
  assistantReads?: boolean;
  /** "w grudniu": the month (or days of the period) of this chat, for "Tylko w grudniu" / "Na stałe". */
  only?: string;
  /** The message being written; kept outside, so closing the chat does not lose it. */
  text: string;
  onTextChange: (text: string) => void;
}) {
  const scoped = useRequests({ companyId, periodId, month });
  const { requests, params, refresh } = scoped;
  // Lasting requests from earlier months belong to those months' chats ("Twoje prośby" lists them here too).
  const list = scoped.list.filter((r) => !isCarried(r));
  const queryClient = useQueryClient();
  const create = useCreateMyRequest({ mutation: { onSuccess: refresh } });
  const remove = useDeleteMyRequest({ mutation: { onSuccess: refresh } });
  const [removing, setRemoving] = useState<string | null>(null);
  const update = useUpdateMyRequest({ mutation: { onSuccess: refresh } });
  // "Zaznacz „nie mogę”": the same save as a tap in the calendar, so the calendar screens refresh too.
  const markCannot = useSaveMyCalendar({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({
          predicate: (query) =>
            String(query.queryKey[0]).startsWith("/api/me/"),
        }),
    },
  });
  const failure =
    update.error ?? remove.error ?? create.error ?? markCannot.error;
  // A question the assistant still remembers waits for an answer: the next message may be it.
  const asking = list.some((r) => r.can_answer);

  const feedRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const changeKey = list.map((r) => `${r.id}:${r.status}`).join(",");
  useEffect(() => {
    // The chat opens at the newest message, also while the drawer is still sliding in.
    const scroll = () => {
      const feed = feedRef.current;
      if (feed && follow.current) feed.scrollTop = feed.scrollHeight;
    };
    scroll();
    const frame = requestAnimationFrame(scroll);
    const timer = setTimeout(scroll, 300);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [changeKey]);

  return (
    <>
      <div
        ref={feedRef}
        onScroll={() => {
          const f = feedRef.current;
          if (f)
            follow.current =
              f.scrollHeight - f.scrollTop - f.clientHeight < 100;
        }}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4"
        role="log"
        aria-label="Twoje prośby o grafiku"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {list.length === 0 && (
          <div className="py-4">
            <h3 className="m-0 mb-2 text-lg font-semibold">
              {assistantReads
                ? "W czym pomóc?"
                : "Co warto uwzględnić w Twoim grafiku?"}
            </h3>
            <p className="m-0 text-sm text-ink-muted">
              {assistantReads
                ? "Zapytaj, na przykład: „Kiedy mam następną zmianę?”. Albo napisz prośbę: „W piątki wolę pracować rano”. Prośby zapiszę w „Twoich prośbach”."
                : "Na przykład: „W piątki wolę pracować rano”. Prośba trafi do „Twoich próśb” i do kierownika."}
            </p>
          </div>
        )}
        <ol className="m-0 grid list-none gap-6 p-0">
          {list.map((request) => (
            <li key={request.id} className="grid gap-2">
              <ChatMessage from="user" date={request.created_at}>
                <p className="m-0 whitespace-pre-wrap">{request.text}</p>
              </ChatMessage>
              <div className="flex flex-wrap items-center justify-end gap-x-2 text-xs text-ink-muted">
                <span>
                  {request.status === "answered" && request.question
                    ? "Asystent dopytuje"
                    : request.status === "answered"
                      ? "Odpowiedź asystenta"
                      : request.status === "superseded"
                        ? "Historia prośby"
                        : request.status === "rejected"
                          ? "Odrzucona"
                          : request.status === "new" && assistantReads
                            ? "Wysłane"
                            : "Zapisane w Twoich prośbach"}
                </span>
                {editable && !isSaved(request) && (
                  <RemoveControl
                    asking={removing === request.id}
                    busy={remove.isPending}
                    onAsk={() => setRemoving(request.id)}
                    onCancel={() => setRemoving(null)}
                    onRemove={() =>
                      remove.mutate(
                        { requestId: request.id },
                        { onSettled: () => setRemoving(null) },
                      )
                    }
                  />
                )}
              </div>
              <RequestReply request={request} assistantReads={assistantReads}>
                <RequestStatus
                  request={request}
                  editable={editable && request.status !== "superseded"}
                  waiting={editable && Boolean(request.can_answer)}
                  busy={update.isPending}
                  marking={markCannot.isPending}
                  only={only}
                  onLasting={(lasting) =>
                    update.mutate({ requestId: request.id, data: { lasting } })
                  }
                  onRewrite={(newText) => {
                    follow.current = true;
                    update.mutate({
                      requestId: request.id,
                      data: { text: newText },
                    });
                  }}
                  onToManager={() =>
                    update.mutate({
                      requestId: request.id,
                      data: { understood: false },
                    })
                  }
                  onMarkCannot={(mark) =>
                    markCannot.mutate({
                      data: {
                        company_id: companyId,
                        days: mark.days.map((date) => ({
                          date,
                          state: "cannot",
                          from_time: mark.from_time ?? null,
                          to_time: mark.to_time ?? null,
                        })),
                      },
                    })
                  }
                />
                <HoursProposals request={request} />
              </RequestReply>
            </li>
          ))}
        </ol>
      </div>
      <div className="grid shrink-0 gap-2 border-t border-grid px-4 pt-3 pb-2">
        {failure && (
          <InlineError>{errorMessage(failure, NETWORK_PROBLEM)}</InlineError>
        )}
        {editable ? (
          <ChatComposer
            text={text}
            onChange={onTextChange}
            label={assistantReads ? "Twoja wiadomość" : "Twoja prośba"}
            sendLabel={assistantReads ? "Wyślij" : "Wyślij prośbę"}
            enterSends={false}
            placeholder={
              asking
                ? "Odpowiedz asystentowi…"
                : assistantReads
                  ? "Zapytaj albo opisz prośbę…"
                  : "Opisz swoją prośbę…"
            }
            disabled={requests.isPending || requests.isError}
            sending={create.isPending}
            onSend={() => {
              if (!text.trim() || create.isPending) return;
              follow.current = true;
              create.mutate(
                { data: { ...params, text: text.trim() } },
                { onSuccess: () => onTextChange("") },
              );
            }}
            footer={assistantReads ? undefined : "Wiadomość dla kierownika."}
          />
        ) : (
          <p className="m-0 text-sm text-ink-muted">
            Prośby na ten okres są już zamknięte. Jeśli coś się zmieniło,
            porozmawiaj z kierownikiem.
          </p>
        )}
        <Disclosure
          className="text-xs text-ink-muted"
          summary="O prośbach i Twoich danych"
        >
          <p className="mt-0 mb-2 leading-relaxed">
            W jednej wiadomości możesz zapytać o coś i napisać do trzech próśb.
            Napisz też powód, jeśli jest ważny. Dyspozycje zaznacz w kalendarzu.
            Prośba „Na stałe” liczy się też w kolejnych miesiącach, dopóki jej
            nie zakończysz w „Twoich prośbach”.{" "}
            {!periodId &&
              "Prośba dotyczy tego miesiąca. Kierownik weźmie ją pod uwagę, gdy będzie układać na niego grafik. "}
            {assistantReads
              ? "Asystent AI (zewnętrzna usługa) czyta Twoją wiadomość, Twoje wcześniejsze prośby oraz imiona osób i nazwy zmian w lokalu. Żeby odpowiedzieć, sprawdza to, co widzisz w aplikacji: Twój grafik, wypłatę, dyspozycje, prośby, zmiany do wzięcia i powiadomienia. Nie dostaje numerów telefonów. Niczego nie zmienia sam: nie układa grafiku i nie zmienia kalendarza. Kierownik i jego asystent AI widzą Twoje dyspozycje, zapisane prośby (z pytaniami asystenta o nie) i to, co przekażesz kierownikowi. Reszty rozmowy nie widzą."
              : "Przeczyta to tylko kierownik."}
          </p>
        </Disclosure>
      </div>
    </>
  );
}

export function RequestsSection(props: Parameters<typeof RequestsWindow>[0]) {
  return (
    <RequestsWindow
      key={`${props.companyId}:${props.periodId ?? props.month}`}
      {...props}
    />
  );
}

function RequestReply({
  request,
  assistantReads,
  children,
}: {
  request: MyRequestOut;
  assistantReads: boolean;
  children: ReactNode;
}) {
  return request.status === "interpreted" ||
    request.status === "answered" ||
    (request.status === "new" && assistantReads) ? (
    <ChatMessage from="assistant">{children}</ChatMessage>
  ) : (
    <div className="border-l-2 border-line pl-3">{children}</div>
  );
}
