import { useQueryClient } from "@tanstack/react-query";
import {
  ListChecks,
  Check,
  Users,
  CalendarSearch,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  getAssistantHistoryQueryKey,
  useApplyAssistantCommand,
  useAssistantHistory,
  useDismissAssistantCommand,
  useLocationInstructions,
  useSendAssistantCommand,
  type assistantHistoryResponse,
} from "../../api/generated/assistant/assistant";
import type { AssistantCommandOut } from "../../api/generated/model";
import {
  ChatComposer,
  ChatMessage,
  ChatTyping,
} from "../../components/assistant/Chat";
import { Button } from "../../components/ui/button";
import { Disclosure } from "../../components/ui/disclosure";
import { InlineError, Loading } from "../../components/ui/status";
import { errorMessage, NETWORK_PROBLEM } from "../../lib/api-error";
import { useManager } from "./ManagerContext";

const WAIT_MS = 90_000;
const MEMORY_MS = 24 * 60 * 60 * 1000;
const STARTERS = [
  {
    icon: ListChecks,
    title: "Ustal odpoczynek",
    text: "Ustaw co najmniej 11 godzin odpoczynku między zmianami.",
  },
  {
    icon: Users,
    title: "Ustal pracę osób",
    text: "Chcę ustalić, kto powinien pracować razem, a kto osobno.",
  },
  {
    icon: CalendarSearch,
    title: "Sprawdź dyspozycje",
    text: "Kto jeszcze nie wysłał dyspozycji?",
  },
];

/**
 * The conversation itself, shown in the drawer that slides in from the right (`AssistantDrawer`). Approved
 * proposals land in the period's agreements (`AssistantRulesTable`). The history is kept on the server;
 * model memory remains bounded independently of it.
 */
export function AssistantPanel({
  locationId,
  periodId,
  initialText = "",
}: {
  locationId: string;
  periodId?: string;
  initialText?: string;
}) {
  const { readOnly: accountReadOnly } = useManager();
  const queryClient = useQueryClient();
  const instructions = useLocationInstructions(
    locationId,
    periodId ? { period_id: periodId } : undefined,
  );
  const history = useAssistantHistory(locationId, {
    query: {
      refetchInterval: (query) => {
        const result = query.state.data;
        return result?.status === 200 &&
          result.data.some(
            (row) =>
              row.status === "queued" &&
              Date.now() - Date.parse(row.created_at) < WAIT_MS,
          )
          ? 1500
          : false;
      },
    },
  });
  const send = useSendAssistantCommand();
  const [text, setText] = useState(initialText);
  const [now, setNow] = useState(Date.now);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const data =
    instructions.data?.status === 200 ? instructions.data.data : undefined;
  const readOnly = accountReadOnly || !!data?.closed;
  const rows = history.data?.status === 200 ? history.data.data : [];
  const enabled = data?.assistant_enabled ?? false;
  const pendingUntil = Math.max(
    0,
    ...rows
      .filter((r) => r.status === "queued")
      .map((r) => Date.parse(r.created_at) + WAIT_MS),
  );
  const waiting = pendingUntil > now;
  const remembered = new Set(
    rows
      .filter(
        (row) =>
          row.status !== "queued" &&
          row.rule_set_id === data?.rule_set_id &&
          Date.parse(row.created_at) >= now - MEMORY_MS,
      )
      .slice(-6)
      .map((row) => row.id),
  );
  const changeKey = rows.map((r) => `${r.id}:${r.status}`).join(",");

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    const refresh = () => setNow(Date.now());
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  useEffect(() => {
    if (pendingUntil <= Date.now()) return;
    const timer = setTimeout(
      () => setNow(Date.now()),
      pendingUntil - Date.now() + 20,
    );
    return () => clearTimeout(timer);
  }, [pendingUntil]);
  useEffect(() => {
    // Open at the newest message, also when the drawer is still sliding in.
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
  }, [changeKey, send.isPending]);

  const remember = async (row: AssistantCommandOut) => {
    const queryKey = getAssistantHistoryQueryKey(locationId);
    await queryClient.cancelQueries({ queryKey });
    queryClient.setQueryData<assistantHistoryResponse>(queryKey, (old) => ({
      status: 200,
      headers: old?.headers ?? new Headers(),
      data: [
        ...(old?.status === 200 ? old.data : []).filter((r) => r.id !== row.id),
        row,
      ]
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .slice(-50),
    }));
    void queryClient.invalidateQueries();
  };
  const draft = (value: string) => {
    setText(value);
    requestAnimationFrame(() => inputRef.current?.focus());
  };
  const submit = () => {
    if (readOnly || !enabled || send.isPending || waiting || !text.trim())
      return;
    follow.current = true;
    send.mutate(
      { locationId, data: { text: text.trim(), period_id: periodId } },
      {
        onSuccess: async (response) => {
          if (response.status !== 201) return;
          await remember(response.data);
          setText("");
          requestAnimationFrame(() => inputRef.current?.focus());
        },
      },
    );
  };

  return (
    <section
      aria-label="Asystent grafiku"
      className="flex min-h-0 flex-1 flex-col"
    >
      <div
        ref={feedRef}
        onScroll={() => {
          const f = feedRef.current;
          if (f)
            follow.current =
              f.scrollHeight - f.scrollTop - f.clientHeight < 100;
        }}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4"
        role="log"
        aria-label="Rozmowa z asystentem"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {history.isPending && <Loading>Wczytuję rozmowę…</Loading>}
        {history.isError && (
          <div className="grid gap-3">
            <InlineError>
              {errorMessage(history.error, "Nie udało się wczytać rozmowy.")}
            </InlineError>
            <Button
              variant="secondary"
              size="normal"
              onClick={() => void history.refetch()}
            >
              Wczytaj ponownie
            </Button>
          </div>
        )}
        {!history.isPending &&
          !history.isError &&
          rows.length === 0 &&
          !send.isPending && (
            <div className="flex min-h-full flex-col justify-center gap-4">
              <div>
                <h3 className="m-0 text-xl font-semibold tracking-tight">
                  W czym mogę pomóc?
                </h3>
                <p className="mt-2 mb-0 text-sm leading-relaxed text-ink-muted">
                  Zapytaj o grafik, dyspozycje i godziny albo opisz zasadę
                  układania grafiku.
                </p>
              </div>
              <div className="grid gap-2">
                {STARTERS.map(({ icon: Icon, title, text }) => (
                  <button
                    key={title}
                    type="button"
                    disabled={!enabled || readOnly}
                    onClick={() => draft(text)}
                    className="group flex min-h-(--touch-main) cursor-pointer items-center gap-3 rounded-md border border-grid bg-surface p-3 text-left transition-colors hover:border-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Icon
                      size={22}
                      strokeWidth={1.6}
                      className="shrink-0 text-accent"
                      aria-hidden="true"
                    />
                    <span className="text-sm font-medium">{title}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        <ol className="m-0 grid list-none gap-6 p-0">
          {rows.map((row, i) => (
            <li key={row.id} className="grid gap-5">
              {(i === 0 ||
                new Date(row.created_at).toLocaleDateString("pl-PL") !==
                  new Date(rows[i - 1].created_at).toLocaleDateString(
                    "pl-PL",
                  )) && (
                <p className="m-0 text-center text-xs text-ink-muted">
                  {new Date(row.created_at).toLocaleDateString("pl-PL", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })}
                </p>
              )}
              {row.status !== "queued" &&
                !remembered.has(row.id) &&
                (i === 0 || remembered.has(rows[i - 1].id)) && (
                  <p className="m-0 text-center text-xs text-ink-muted">
                    Starsze wiadomości. Asystent ich nie pamięta.
                  </p>
                )}
              {row.period_label &&
                (i === 0 ||
                  rows[i - 1].period_label !== row.period_label ||
                  !!rows[i - 1].consumed_at !== !!row.consumed_at) && (
                  <p className="m-0 text-center text-xs text-ink-muted">
                    {row.period_label}
                    {row.consumed_at ? " · wykorzystane" : ""}
                  </p>
                )}
              <ChatMessage from="user" date={row.created_at}>
                <p className="m-0 whitespace-pre-wrap">{row.text}</p>
              </ChatMessage>
              <ChatMessage from="assistant">
                <CommandReply
                  data={row}
                  late={now - Date.parse(row.created_at) >= WAIT_MS}
                  readOnly={readOnly || !!row.consumed_at}
                  expired={now >= Date.parse(row.expires_at)}
                  onChanged={remember}
                  onRetry={() => void history.refetch()}
                  onRewrite={() => draft(row.text)}
                />
              </ChatMessage>
            </li>
          ))}
          {send.isPending && (
            <li className="grid gap-5">
              <ChatMessage from="user">
                <p className="m-0 whitespace-pre-wrap">
                  {send.variables?.data.text}
                </p>
              </ChatMessage>
              <ChatMessage from="assistant">
                <ChatTyping>Wysyłam wiadomość…</ChatTyping>
              </ChatMessage>
            </li>
          )}
        </ol>
      </div>
      <div className="shrink-0 border-t border-grid bg-surface px-4 pt-3 pb-2">
        {send.isError && (
          <div className="mb-3">
            <InlineError>
              {errorMessage(send.error, NETWORK_PROBLEM)} Tekst pozostał w polu
              wiadomości.
            </InlineError>
          </div>
        )}
        {instructions.isError && (
          <InlineError>
            Nie udało się sprawdzić dostępności asystenta.{" "}
            <button
              type="button"
              className="min-h-(--touch) cursor-pointer underline"
              onClick={() => void instructions.refetch()}
            >
              Spróbuj ponownie
            </button>
          </InlineError>
        )}
        {data && !enabled && (
          <p className="mt-0 text-sm text-ink-muted">
            Asystent jest wyłączony. Możesz przejrzeć rozmowę i zmienić zasady
            ręcznie.
          </p>
        )}
        {readOnly && (
          <p className="mt-0 text-sm text-ink-muted">
            {data?.closed
              ? "Te ustalenia wykorzystano w opublikowanym grafiku. Zachowano je dla korekt tego okresu."
              : "Masz dostęp tylko do odczytu."}
          </p>
        )}
        <p className="mt-0 mb-2 text-sm font-semibold">
          {data?.period_requested
            ? `Zasady na ${data.period_label}`
            : "Jeszcze bez okresu. Ustalenia zadziałają, gdy klikniesz „Poproś o dyspozycje”."}
        </p>
        <ChatComposer
          text={text}
          onChange={setText}
          onSend={submit}
          sending={send.isPending}
          waiting={waiting}
          inputRef={inputRef}
          disabled={
            readOnly || !enabled || history.isPending || history.isError
          }
          placeholder="Zapytaj albo opisz zasadę…"
          footer="Zmiany zapiszę dopiero, gdy je zatwierdzisz."
        />
        <p className="mt-2 mb-0 text-xs text-ink-muted">
          Claude (AI) czyta Twoje wiadomości. Pamięta do 6 zakończonych z tego
          okresu z ostatnich 24 godzin.
        </p>
        <Disclosure
          className="text-xs text-ink-muted"
          summary="Jak działa asystent"
        >
          <p className="mt-0 mb-2">
            Ty decydujesz: zasada trafia do ustaleń dopiero, gdy ją
            zatwierdzisz. Polecenia o osobach są preferencjami, bez gwarancji
            przydziału.
          </p>
          <p className="mt-0 mb-2">
            Claude czyta też listy zasad, osób i zmian tego lokalu, a żeby
            odpowiedzieć na pytanie, sprawdza w aplikacji to, co Ty widzisz:
            grafik, godziny, oddane zmiany oraz dyspozycje i prośby pracowników.
            Nie dostaje numerów telefonów i niczego nie zmienia sam. Może się
            pomylić, więc ważne dane sprawdź na ekranie. Starszą sprawę opisz
            ponownie. W historii widzisz ostatnie 50 wiadomości.
          </p>
        </Disclosure>
      </div>
    </section>
  );
}

function CommandReply({
  data,
  late,
  readOnly,
  expired,
  onChanged,
  onRetry,
  onRewrite,
}: {
  data: AssistantCommandOut;
  late: boolean;
  expired: boolean;
  readOnly: boolean;
  onChanged: (row: AssistantCommandOut) => Promise<void>;
  onRetry: () => void;
  onRewrite: () => void;
}) {
  const apply = useApplyAssistantCommand();
  const dismiss = useDismissAssistantCommand();
  if (data.status === "queued")
    return late ? (
      <div className="grid gap-2">
        <p className="m-0">Odpowiedź zajmuje więcej czasu niż zwykle.</p>
        <div>
          <Button variant="secondary" size="normal" onClick={onRetry}>
            Sprawdź odpowiedź
          </Button>
        </div>
      </div>
    ) : (
      <ChatTyping />
    );
  if (data.status === "failed" || data.status === "unavailable")
    return (
      <div className="grid gap-3">
        <p role="alert" className="m-0">
          {data.status === "failed"
            ? "Nie udało się przygotować odpowiedzi. Nic się nie zmieniło."
            : "Asystent jest teraz niedostępny. Spróbuj później."}
        </p>
        <div>
          <Button
            variant="secondary"
            size="normal"
            disabled={readOnly}
            onClick={onRewrite}
          >
            Wpisz ponownie
          </Button>
        </div>
      </div>
    );
  const applied = data.status === "applied";
  const dismissed = data.status === "dismissed";
  const closedProposal = data.status === "ready" && !!data.consumed_at;
  const needsRefresh =
    data.status === "ready" &&
    data.lines.length > 0 &&
    expired &&
    !closedProposal;
  const busy = readOnly || apply.isPending || dismiss.isPending;
  const done = {
    onSuccess: async (response: { status: number; data: unknown }) => {
      if (response.status === 200)
        await onChanged(response.data as AssistantCommandOut);
    },
  };
  return (
    <>
      {data.reply && <p className="m-0 whitespace-pre-wrap">{data.reply}</p>}
      {data.informational && (
        <p className="m-0 text-sm text-ink-muted">
          Asystent może się pomylić. Ważne dane sprawdź w aplikacji, na przykład
          w zakładkach „Grafik” i „Dyspozycje” albo w „Godzinach”.
        </p>
      )}
      {data.question && <p className="m-0 font-semibold">{data.question}</p>}
      {data.lines.length > 0 && (
        <div className="overflow-hidden rounded-md border border-grid">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-grid bg-paper px-4 py-3">
            <span className="text-sm font-semibold">Propozycja zmian</span>
            {applied ? (
              <span className="flex items-center gap-1 whitespace-nowrap text-xs font-semibold text-prefer">
                <Check size={16} aria-hidden="true" /> Zatwierdzona
              </span>
            ) : dismissed ? (
              <span className="flex items-center gap-1 whitespace-nowrap text-xs text-ink-muted">
                <X size={16} aria-hidden="true" /> Odrzucona
              </span>
            ) : (
              <span className="text-xs text-ink-muted">
                {closedProposal
                  ? "Okres zamknięty"
                  : needsRefresh
                    ? "Wygasła"
                    : "Do zatwierdzenia"}
              </span>
            )}
          </div>
          <ul className="m-0 grid list-none gap-3 p-4">
            {data.lines.map((line, i) => (
              <li key={`${i}:${line}`} className="flex gap-3">
                <span
                  aria-hidden="true"
                  className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
                >
                  {i + 1}
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
          {closedProposal && (
            <p className="m-0 border-t border-grid p-4 text-sm text-ink-muted">
              Grafik tego okresu został opublikowany. Ta propozycja nie została
              zatwierdzona.
            </p>
          )}
          {needsRefresh && (
            <div className="grid gap-2 border-t border-grid p-4">
              <p className="m-0 text-sm text-ink-muted">
                Propozycja wygasła po 24 godzinach. Wyślij polecenie ponownie,
                aby sprawdzić aktualne dane.
              </p>
              <Button
                variant="secondary"
                size="normal"
                disabled={readOnly}
                onClick={onRewrite}
              >
                Przygotuj ponownie
              </Button>
            </div>
          )}
          {data.can_apply &&
            data.status === "ready" &&
            !needsRefresh &&
            !closedProposal && (
              <div className="flex flex-wrap gap-2 border-t border-grid px-4 py-3">
                <Button
                  size="normal"
                  disabled={busy}
                  onClick={() => apply.mutate({ commandId: data.id }, done)}
                >
                  <Check size={18} aria-hidden="true" />
                  {apply.isPending ? "Zapisuję…" : "Zatwierdź zmiany"}
                </Button>
                <Button
                  variant="quiet"
                  size="normal"
                  disabled={busy}
                  onClick={() => dismiss.mutate({ commandId: data.id }, done)}
                >
                  Odrzuć
                </Button>
              </div>
            )}
        </div>
      )}
      {applied && (
        <p role="status" className="m-0 text-sm text-prefer">
          Zapisane w ustaleniach. Tam możesz je zmienić albo usunąć.
        </p>
      )}
      {dismissed && (
        <p role="status" className="m-0 text-sm text-ink-muted">
          Propozycja odrzucona. Ustawienia pozostały bez zmian.
        </p>
      )}
      {data.notes.length > 0 && (
        <ul className="m-0 grid list-none gap-2 rounded-md bg-prefer-not-soft p-3 text-sm text-prefer-not">
          {data.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
      {data.effects.length > 0 && (
        <Disclosure
          className="text-sm text-ink-muted"
          summary="Porównanie z chwili przygotowania propozycji"
        >
          <ul className="mt-0 grid gap-2 pl-5">
            {data.effects.map((effect, i) => (
              <li key={i}>{effect}</li>
            ))}
          </ul>
        </Disclosure>
      )}
      {!data.reply &&
        !data.question &&
        !data.lines.length &&
        !applied &&
        !dismissed && (
          <p className="m-0 text-ink-muted">
            Nie mam jeszcze propozycji. Opisz dokładniej, co chcesz zmienić.
          </p>
        )}
      {(apply.isError || dismiss.isError) && (
        <InlineError>
          {errorMessage(apply.error ?? dismiss.error, NETWORK_PROBLEM)}
        </InlineError>
      )}
    </>
  );
}
