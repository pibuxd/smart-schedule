import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  getMyRequestsQueryKey,
  useCreateMyRequest,
  useDeleteMyRequest,
  useMyRequests,
  useSaveMyCalendar,
  useUpdateMyRequest,
} from "../../api/generated/availability/availability";
import type { MyRequestOut } from "../../api/generated/model";
import {
  ChatComposer,
  ChatMessage,
  ChatTyping,
} from "../../components/assistant/Chat";
import { Button } from "../../components/ui/button";
import { Disclosure } from "../../components/ui/disclosure";
import { InlineError } from "../../components/ui/status";
import { errorMessage, NETWORK_PROBLEM } from "../../lib/api-error";
import { useEmployeeChat, useScreenChatScope } from "./employee-chat";
import { HoursProposals } from "./HoursProposals";

/** Requests that count: understood by the assistant (they reach the generator) or left for the manager. */
const isSaved = (request: MyRequestOut) =>
  request.status === "interpreted" || request.status === "needs_manager";

// How long a fresh request is shown as "being read" before we stop asking the server.
const READING_MS = 60_000;

/** "14.12" for "2026-12-14". */
const shortDate = (iso: string) =>
  `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;

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
function Question({ question, waiting }: { question: string; waiting: boolean }) {
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
  onRewrite,
  onToManager,
  onMarkCannot,
}: {
  request: MyRequestOut;
  editable: boolean;
  /** The newest message of the chat: an open question waits for the next one. */
  waiting?: boolean;
  busy: boolean;
  marking: boolean;
  onRewrite: (text: string) => void;
  onToManager: () => void;
  onMarkCannot: (days: string[]) => void;
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
    const days = request.unmarked_days;
    return (
      <div className="grid gap-2">
        <Reply request={request} />
        <p className="m-0">
          <span className="font-semibold">Tak to zrozumieliśmy: </span>
          {request.summary}
        </p>
        <p className="m-0 text-sm text-ink-muted">
          Generator grafiku spróbuje to spełnić. Kalendarz się nie zmienia.
        </p>
        <Notes notes={request.notes} />
        {editable && days.length > 0 && (
          <div className="grid gap-2 rounded-md border border-line p-3">
            <p className="m-0 text-sm">
              W kalendarzu te dni są nadal do pracy:{" "}
              {days.map(shortDate).join(", ")}.
            </p>
            <div>
              <Button
                variant="secondary"
                size="normal"
                disabled={busy || marking}
                onClick={() => onMarkCannot(days)}
              >
                {marking ? "Zapisuję…" : "Zaznacz „nie mogę”"}
              </Button>
            </div>
          </div>
        )}
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
    return <ChatTyping>Czytamy Twoją wiadomość…</ChatTyping>;
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

/**
 * "Twoje prośby" under the calendar: only the requests that count (understood by the assistant, or left for the
 * manager to read); each can be corrected or removed here. The conversation itself is in the chat that slides in
 * from the right (`EmployeeChatProvider`); while this window is on screen, the "Asystent" button opens it on this
 * window's month too. A request belongs to the period the manager asked for (`periodId`), or, before that, to the
 * month on the screen (`month`, its first day): the manager sees it in every period that covers that month.
 */
function RequestsWindow({
  companyId,
  periodId,
  month,
  editable,
  assistantReads = false,
}: {
  companyId: string;
  periodId?: string;
  month?: string;
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
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(
    null,
  );
  const chatOpen = chat?.open ?? false;
  const openChat = () => chat?.openChat({ periodId, month, editable });
  const saved = list.filter(isSaved);
  const reading = assistantReads && list.some((r) => r.status === "new");
  // The newest message left a trace only in the chat: say so in the window, so it does not look lost.
  const last = list.at(-1);
  const notSaved =
    last && (last.status === "rejected" || last.status === "answered")
      ? last
      : undefined;
  const failure = update.error ?? remove.error;

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
      {!requests.isPending && !requests.isError && saved.length === 0 && (
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
                <div className="py-2 pr-2">
                  <form
                    className="grid gap-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      update.mutate(
                        {
                          requestId: request.id,
                          data: { text: editing.text.trim() },
                        },
                        {
                          onSuccess: () => setEditing(null),
                        },
                      );
                    }}
                  >
                    <label className="grid gap-1">
                      Treść prośby
                      <textarea
                        className="rounded-md border-2 border-ink p-2"
                        maxLength={1000}
                        rows={3}
                        value={editing.text}
                        onChange={(e) =>
                          setEditing({ id: request.id, text: e.target.value })
                        }
                      />
                    </label>
                    <p className="m-0 text-sm text-ink-muted">
                      Kierownik zobaczy poprawioną treść. Jego wcześniejsza
                      decyzja i nadana prośbie ważność pozostaną w mocy.{" "}
                      {assistantReads &&
                        "Po zmianie tekstu zewnętrzny asystent AI przeczyta prośbę ponownie."}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="submit"
                        disabled={
                          update.isPending ||
                          !editing.text.trim() ||
                          editing.text.trim() === request.text
                        }
                      >
                        Zapisz prośbę
                      </Button>
                      <Button
                        type="button"
                        variant="quiet"
                        disabled={update.isPending}
                        onClick={() => setEditing(null)}
                      >
                        Anuluj
                      </Button>
                    </div>
                  </form>
                </div>
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
                    </span>
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
      {reading && <ChatTyping>Asystent czyta Twoją prośbę…</ChatTyping>}
      {notSaved && !chatOpen && (
        <p className="m-0 text-sm text-ink-muted">
          {notSaved.status === "rejected"
            ? "Twoja ostatnia wiadomość została odrzucona i nie jest prośbą."
            : notSaved.question
              ? "Asystent ma pytanie do Twojej ostatniej wiadomości."
              : "Asystent odpowiedział na Twoją ostatnią wiadomość."}{" "}
          <button
            type="button"
            className="min-h-(--touch) cursor-pointer font-semibold text-accent underline"
            onClick={openChat}
          >
            {notSaved.question ? "Odpowiedz" : "Pokaż odpowiedź"}
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
  text,
  onTextChange,
}: {
  companyId: string;
  periodId?: string;
  month?: string;
  editable: boolean;
  assistantReads?: boolean;
  /** The message being written; kept outside, so closing the chat does not lose it. */
  text: string;
  onTextChange: (text: string) => void;
}) {
  const { requests, list, params, refresh } = useRequests({
    companyId,
    periodId,
    month,
  });
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
  // The assistant asked about the newest message: the next one answers it.
  const lastId = list.at(-1)?.id;
  const asking = Boolean(
    list.at(-1)?.status === "answered" && list.at(-1)?.question,
  );

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
                  waiting={editable && request.id === lastId}
                  busy={update.isPending}
                  marking={markCannot.isPending}
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
                  onMarkCannot={(days) =>
                    markCannot.mutate({
                      data: {
                        company_id: companyId,
                        days: days.map((date) => ({
                          date,
                          state: "cannot",
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
            footer={
              assistantReads
                ? "Czyta to asystent AI (zewnętrzna usługa), kierownik i jego asystent."
                : "Wiadomość dla kierownika."
            }
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
            W jednej wiadomości możesz zapytać o coś i napisać do trzech
            próśb. Napisz też powód, jeśli jest ważny. Dyspozycje zaznacz w
            kalendarzu.{" "}
            {!periodId &&
              "Prośba dotyczy tego miesiąca. Kierownik weźmie ją pod uwagę, gdy będzie układać na niego grafik. "}
            {assistantReads
              ? "Asystent AI (zewnętrzna usługa) czyta Twoją wiadomość, Twoje wcześniejsze prośby oraz imiona osób i nazwy zmian w lokalu. Żeby odpowiedzieć, sprawdza to, co widzisz w aplikacji: Twój grafik, dyspozycje, prośby, zmiany do wzięcia i powiadomienia. Nie dostaje numerów telefonów. Niczego nie zmienia sam: nie układa grafiku i nie zmienia kalendarza. Prośby czyta też kierownik, a gdy kierownik pyta swojego asystenta, ten też może przeczytać Twoje prośby i dyspozycje. Nie wpisuj tu nic, czego nie chcesz przekazać kierownikowi."
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
