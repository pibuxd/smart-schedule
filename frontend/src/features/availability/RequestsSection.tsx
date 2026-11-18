import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  getMyRequestsQueryKey,
  useCreateMyRequest,
  useDeleteMyRequest,
  useMyRequests,
  useUpdateMyRequest,
} from "../../api/generated/availability/availability";
import type { MyRequestOut } from "../../api/generated/model";
import {
  ChatComposer,
  ChatMessage,
  ChatTyping,
} from "../../components/assistant/Chat";
import { Button } from "../../components/ui/button";
import { Drawer } from "../../components/ui/drawer";
import { InlineError } from "../../components/ui/status";
import { errorMessage, NETWORK_PROBLEM } from "../../lib/api-error";

/** Requests that count: understood by the assistant (they reach the generator) or left for the manager. */
const isSaved = (request: MyRequestOut) =>
  request.status === "interpreted" || request.status === "needs_manager";

// How long a fresh request is shown as "being read" before we stop asking the server.
const READING_MS = 60_000;

/** How the request was understood, in plain words, with a way to say "that is not what I meant". */
function RequestStatus({
  request,
  editable,
  busy,
  onWrong,
}: {
  request: MyRequestOut;
  editable: boolean;
  busy: boolean;
  onWrong: () => void;
}) {
  if (request.status === "rejected")
    return (
      <p className="m-0 text-sm text-ink-muted">
        {request.summary ?? "Ta prośba została odrzucona."}
      </p>
    );
  if (request.status === "superseded") {
    return (
      <p className="m-0 text-sm text-ink-muted">
        Ta prośba została zastąpiona nowszą. Nie wpływa już na układanie
        grafiku.
      </p>
    );
  }
  if (request.status === "answered" && request.summary) {
    return (
      <div className="grid gap-2">
        <p className="m-0">{request.summary}</p>
        <p className="m-0 text-sm">
          To odpowiedź asystenta. Przekaż wiadomość, aby dodać ją do listy próśb
          kierownika.
        </p>
        {editable && (
          <div>
            <Button
              variant="quiet"
              size="normal"
              disabled={busy}
              onClick={onWrong}
            >
              Przekaż kierownikowi
            </Button>
          </div>
        )}
      </div>
    );
  }
  if (request.status === "interpreted" && request.summary) {
    return (
      <div className="grid gap-2">
        <p className="m-0">
          <span className="font-semibold">Tak to zrozumieliśmy: </span>
          {request.summary}
        </p>
        <p className="m-0 text-sm">
          To preferencja, którą generator spróbuje spełnić. Nie zmienia
          kalendarza dyspozycji. Jeśli nie możesz pracować, zaznacz „nie mogę” w
          kalendarzu.
        </p>
        {editable && (
          <div>
            <Button
              variant="quiet"
              size="normal"
              disabled={busy}
              onClick={onWrong}
            >
              Nie o to mi chodziło
            </Button>
          </div>
        )}
      </div>
    );
  }
  if (request.status === "new")
    return <ChatTyping>Czytamy Twoją prośbę…</ChatTyping>;
  return (
    <p className="m-0 text-sm text-ink-muted">
      Kierownik przeczyta tę prośbę sam.
    </p>
  );
}

/**
 * "Twoje prośby": requests in words, only for what the calendar cannot say. The person writes in a chat that
 * slides in from the right; a request the assistant understood (or one left for the manager to read) lands in
 * the "Twoje prośby" window, where it can be edited or removed. When the assistant is on (`assistantReads`),
 * the text also goes to an outside AI service, and the chat says so.
 * A request belongs to the period the manager asked for (`periodId`), or, before that, to the month on the
 * screen (`month`, its first day): the manager sees it in every period that covers that month.
 */
function RequestsChat({
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
  const create = useCreateMyRequest({ mutation: { onSuccess: refresh } });
  const remove = useDeleteMyRequest({ mutation: { onSuccess: refresh } });
  const [removing, setRemoving] = useState<string | null>(null);
  const update = useUpdateMyRequest({ mutation: { onSuccess: refresh } });
  const [text, setText] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(
    null,
  );
  const list = (requests.data?.data as MyRequestOut[] | undefined) ?? [];
  const saved = list.filter(isSaved);
  const reading = assistantReads && list.some((r) => r.status === "new");
  // The newest message left a trace only in the chat: say so in the window, so it does not look lost.
  const last = list.at(-1);
  const notSaved =
    last && (last.status === "rejected" || last.status === "answered")
      ? last
      : undefined;

  const feedRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const changeKey = list.map((r) => `${r.id}:${r.status}`).join(",");
  useEffect(() => {
    const feed = feedRef.current;
    if (feed && follow.current) feed.scrollTop = feed.scrollHeight;
  }, [changeKey, chatOpen]);

  const removeControl = (request: MyRequestOut) =>
    removing === request.id ? (
      <span className="flex flex-wrap items-center justify-end gap-1">
        <span className="text-sm font-semibold">Usunąć tę prośbę?</span>
        <Button
          variant="quiet"
          size="normal"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(
              { requestId: request.id },
              { onSettled: () => setRemoving(null) },
            )
          }
        >
          Tak, usuń
        </Button>
        <Button variant="quiet" size="normal" onClick={() => setRemoving(null)}>
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
        onClick={() => setRemoving(request.id)}
      >
        <Trash2 size={18} aria-hidden="true" />
      </Button>
    );
  const failure = update.error ?? remove.error ?? create.error;

  return (
    <section
      aria-labelledby="requests-title"
      className="grid gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="requests-title" className="m-0 text-lg font-semibold">
          Twoje prośby
        </h2>
        {(editable || list.length > 0) && (
          <Button
            variant="secondary"
            size="normal"
            onClick={() => setChatOpen(true)}
          >
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
                        "Po zmianie tekstu zewnętrzny asystent AI (Claude) przeczyta prośbę ponownie."}
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
                        "Generator spróbuje ją spełnić."
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
                      {removeControl(request)}
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
            : "Na ostatnią wiadomość asystent odpowiedział. Nie zapisał jej jako prośby."}{" "}
          <button
            type="button"
            className="min-h-(--touch) cursor-pointer font-semibold text-accent underline"
            onClick={() => setChatOpen(true)}
          >
            Pokaż odpowiedź
          </button>
        </p>
      )}
      {failure && !chatOpen && (
        <InlineError>{errorMessage(failure, NETWORK_PROBLEM)}</InlineError>
      )}

      <Drawer
        open={chatOpen}
        onOpenChange={setChatOpen}
        title={assistantReads ? "Asystent" : "Prośby do kierownika"}
        description={
          assistantReads
            ? "Opisz jedną preferencję układania grafiku."
            : "Napisz prośbę do kierownika."
        }
      >
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
                Co warto uwzględnić w Twoim grafiku?
              </h3>
              <p className="m-0 text-sm text-ink-muted">
                Na przykład: „W piątki wolę pracować rano”.{" "}
                {assistantReads
                  ? "Asystent czyta jedną prośbę naraz i nie dopytuje. Gdy ją zrozumie, zapisze ją w „Twoich prośbach”."
                  : "Prośba trafi do „Twoich próśb” i do kierownika."}
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
                    {request.status === "answered"
                      ? "Odpowiedź asystenta"
                      : request.status === "superseded"
                        ? "Historia prośby"
                        : request.status === "rejected"
                          ? "Odrzucona"
                          : request.status === "new" && assistantReads
                            ? "Wysłane"
                            : "Zapisane w Twoich prośbach"}
                  </span>
                  {editable && !isSaved(request) && removeControl(request)}
                </div>
                <RequestReply request={request} assistantReads={assistantReads}>
                  <RequestStatus
                    request={request}
                    editable={editable && request.status !== "superseded"}
                    busy={update.isPending}
                    onWrong={() =>
                      update.mutate({
                        requestId: request.id,
                        data: { understood: false },
                      })
                    }
                  />
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
              onChange={setText}
              label="Twoja prośba"
              sendLabel="Wyślij prośbę"
              enterSends={false}
              placeholder="Opisz swoją prośbę…"
              disabled={requests.isPending || requests.isError}
              sending={create.isPending}
              onSend={() => {
                if (!text.trim() || create.isPending) return;
                follow.current = true;
                create.mutate(
                  { data: { ...params, text: text.trim() } },
                  { onSuccess: () => setText("") },
                );
              }}
              footer={
                assistantReads
                  ? "Prośbę przeczyta też kierownik."
                  : "Wiadomość dla kierownika."
              }
            />
          ) : (
            <p className="m-0 text-sm text-ink-muted">
              Prośby na ten okres są już zamknięte. Jeśli coś się zmieniło,
              porozmawiaj z kierownikiem.
            </p>
          )}
          <details className="text-xs text-ink-muted">
            <summary className="flex min-h-(--touch) cursor-pointer items-center">
              O prośbach i Twoich danych
            </summary>
            <p className="mt-0 mb-2 leading-relaxed">
              Jedna prośba, jedna sprawa. Napisz też powód, jeśli jest ważny.
              Dyspozycje zaznacz w kalendarzu.{" "}
              {!periodId &&
                "Prośba dotyczy tego miesiąca. Kierownik weźmie ją pod uwagę, gdy będzie układać na niego grafik. "}
              {assistantReads
                ? "Asystent AI (zewnętrzna usługa Claude) czyta tę prośbę, Twoje wcześniejsze prośby oraz nazwy osób i zmian w lokalu. Obsługuje tylko preferencje układania grafiku. Nie układa grafiku ani nie zmienia kalendarza. Prośby czyta też kierownik. Nie wpisuj tu nic, czego nie chcesz mu przekazać."
                : "Przeczyta to tylko kierownik."}
            </p>
          </details>
        </div>
      </Drawer>
    </section>
  );
}

export function RequestsSection(props: Parameters<typeof RequestsChat>[0]) {
  return (
    <RequestsChat
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
