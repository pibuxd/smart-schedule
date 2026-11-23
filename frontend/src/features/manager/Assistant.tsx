import { useQueryClient } from "@tanstack/react-query";
import {
  ListChecks,
  Check,
  Users,
  CalendarSearch,
  FileText,
  Paperclip,
  UserPlus,
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
  useSendAssistantFile,
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
import { RunProgress } from "./ArrangeSchedule";
import { useManager } from "./ManagerContext";

// A list of people takes the model longer to write out than a rule.
const WAIT_MS = 90_000;
const FILE_WAIT_MS = 180_000;
// Same limit as the server (`people_list.MAX_FILE_BYTES`).
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const FILE_TYPES =
  ".csv,.txt,.tsv,.xlsx,.pdf,text/csv,text/plain,application/pdf";
const waitFor = (row: AssistantCommandOut) =>
  row.file_name ? FILE_WAIT_MS : WAIT_MS;
// The assistant reads this many earlier messages of the chat (backend `context.MAX_CONVERSATION`).
const MEMORY_COUNT = 10;
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
  {
    icon: UserPlus,
    title: "Zaproś ludzi z pliku",
    text: "",
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
              Date.now() - Date.parse(row.created_at) < waitFor(row),
          )
          ? 1500
          : false;
      },
    },
  });
  const send = useSendAssistantCommand();
  const sendFile = useSendAssistantFile();
  const sending = send.isPending || sendFile.isPending;
  const [text, setText] = useState(initialText);
  // A file to send with the next message (a list of people to invite).
  const [file, setFile] = useState<File | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
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
      .map((r) => Date.parse(r.created_at) + waitFor(r)),
  );
  const waiting = pendingUntil > now;
  const remembered = new Set(
    rows
      .filter(
        (row) =>
          row.status !== "queued" && row.rule_set_id === data?.rule_set_id,
      )
      .slice(-MEMORY_COUNT)
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
  }, [changeKey, sending]);

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
  const chooseFile = (chosen: File | undefined) => {
    setFileProblem(null);
    if (!chosen) return;
    if (chosen.size > MAX_FILE_BYTES) {
      setFileProblem(
        "Plik jest za duży. Najwyżej 2 MB: podziel listę na mniejsze części.",
      );
      return;
    }
    setFile(chosen);
    requestAnimationFrame(() => inputRef.current?.focus());
  };
  const submit = () => {
    if (readOnly || !enabled || sending || waiting || !(text.trim() || file))
      return;
    follow.current = true;
    const sent = {
      onSuccess: async (response: { status: number; data: unknown }) => {
        if (response.status !== 201) return;
        await remember(response.data as AssistantCommandOut);
        setText("");
        setFile(null);
        requestAnimationFrame(() => inputRef.current?.focus());
      },
    };
    if (file) {
      sendFile.mutate(
        {
          locationId,
          data: { file, text: text.trim(), period_id: periodId },
        },
        sent,
      );
    } else {
      send.mutate(
        { locationId, data: { text: text.trim(), period_id: periodId } },
        sent,
      );
    }
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
          !sending && (
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
                    onClick={() =>
                      text ? draft(text) : fileRef.current?.click()
                    }
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
                {row.file_name && <FileChip name={row.file_name} />}
                <p className="m-0 whitespace-pre-wrap">{row.text}</p>
              </ChatMessage>
              <ChatMessage from="assistant">
                <CommandReply
                  data={row}
                  locationId={locationId}
                  late={now - Date.parse(row.created_at) >= waitFor(row)}
                  readOnly={
                    readOnly || (!!row.consumed_at && !row.outside_agreements)
                  }
                  expired={now >= Date.parse(row.expires_at)}
                  onChanged={remember}
                  onRetry={() => void history.refetch()}
                  onRewrite={() => draft(row.text)}
                />
              </ChatMessage>
            </li>
          ))}
          {sending && (
            <li className="grid gap-5">
              <ChatMessage from="user">
                {sendFile.isPending && sendFile.variables && (
                  <FileChip
                    name={
                      sendFile.variables.data.file instanceof File
                        ? sendFile.variables.data.file.name
                        : "plik"
                    }
                  />
                )}
                <p className="m-0 whitespace-pre-wrap">
                  {sendFile.isPending
                    ? sendFile.variables?.data.text
                    : send.variables?.data.text}
                </p>
              </ChatMessage>
              <ChatMessage from="assistant">
                <ChatTyping />
              </ChatMessage>
            </li>
          )}
        </ol>
      </div>
      <div className="shrink-0 border-t border-grid bg-surface px-4 pt-3 pb-2">
        {(send.isError || sendFile.isError) && (
          <div className="mb-3">
            <InlineError>
              {errorMessage(send.error ?? sendFile.error, NETWORK_PROBLEM)}{" "}
              Tekst pozostał w polu wiadomości.
            </InlineError>
          </div>
        )}
        {fileProblem && (
          <div className="mb-3">
            <InlineError>{fileProblem}</InlineError>
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
        <input
          ref={fileRef}
          type="file"
          accept={FILE_TYPES}
          className="sr-only"
          tabIndex={-1}
          aria-label="Plik z listą osób do zaproszenia"
          onChange={(event) => {
            chooseFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <ChatComposer
          text={text}
          onChange={setText}
          onSend={submit}
          sending={sending}
          waiting={waiting}
          inputRef={inputRef}
          disabled={
            readOnly || !enabled || history.isPending || history.isError
          }
          placeholder={
            file ? "Co zrobić z tym plikiem? (nieobowiązkowo)" : "Zapytaj albo opisz zasadę…"
          }
          hasAttachment={!!file}
          attachment={
            file && (
              <div className="flex items-center justify-between gap-2 rounded-md border border-grid bg-paper py-1 pr-1 pl-3 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <FileText size={18} aria-hidden="true" className="shrink-0 text-accent" />
                  <span className="truncate">{file.name}</span>
                </span>
                <Button
                  variant="quiet"
                  size="normal"
                  aria-label={`Usuń plik ${file.name}`}
                  disabled={sending}
                  onClick={() => setFile(null)}
                >
                  <X size={18} aria-hidden="true" />
                </Button>
              </div>
            )
          }
          attachButton={
            <button
              type="button"
              aria-label="Dołącz plik z listą osób"
              title="Dołącz plik z listą osób (CSV, Excel, PDF)"
              disabled={readOnly || !enabled || sending}
              onClick={() => fileRef.current?.click()}
              className="flex h-(--touch) w-(--touch) shrink-0 cursor-pointer items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-accent-soft hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Paperclip size={22} aria-hidden="true" />
            </button>
          }
        />
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
            Asystent to zewnętrzna usługa AI. Czyta Twoje wiadomości i
            dołączone pliki, listy zasad, osób i zmian tego lokalu, a żeby
            odpowiedzieć na
            pytanie, sprawdza w aplikacji to, co Ty widzisz: grafik, godziny,
            oddane zmiany oraz dyspozycje i prośby pracowników. Nie dostaje
            numerów telefonów i niczego nie zmienia sam. Może się pomylić, więc
            ważne dane sprawdź na ekranie. Pamięta {MEMORY_COUNT} ostatnich
            wiadomości z tego okresu, więc starszą sprawę opisz ponownie. W
            historii widzisz ostatnie 50 wiadomości.
          </p>
        </Disclosure>
      </div>
    </section>
  );
}

function CommandReply({
  data,
  locationId,
  late,
  readOnly,
  expired,
  onChanged,
  onRetry,
  onRewrite,
}: {
  data: AssistantCommandOut;
  locationId: string;
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
  // Hours and invitations do not depend on the period's agreements: publishing does not close such a plan.
  const closedProposal =
    data.status === "ready" && !!data.consumed_at && !data.outside_agreements;
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
      {applied && (data.changes_agreements || data.has_hours) && (
        <p role="status" className="m-0 text-sm text-prefer">
          {!data.changes_agreements
            ? "Zapisane. Godziny liczą się od razu, zobaczysz je w „Godzinach”."
            : data.has_hours
              ? "Zapisane. Ustalenia zmienisz w „Ustaleniach”, a godziny w „Godzinach”."
              : "Zapisane w ustaleniach. Tam możesz je zmienić albo usunąć."}
        </p>
      )}
      {applied && data.has_invites && (
        <p role="status" className="m-0 text-sm text-prefer">
          Zaproszenia czekają w „Pracownicy”. SMS-a nie wysyłamy: powiedz tym
          osobom, żeby zalogowały się w Grafikomacie swoim numerem.
        </p>
      )}
      {applied && data.run_id && (
        <RunProgress runId={data.run_id} locationId={locationId} compact />
      )}
      {dismissed && (
        <p role="status" className="m-0 text-sm text-ink-muted">
          {data.has_hours
            ? "Propozycja odrzucona. Nic się nie zmieniło."
            : "Propozycja odrzucona. Ustawienia pozostały bez zmian."}
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

function FileChip({ name }: { name: string }) {
  return (
    <span className="mb-1 flex items-center gap-2 text-sm font-semibold">
      <FileText size={18} aria-hidden="true" className="shrink-0 text-accent" />
      <span className="truncate">{name}</span>
    </span>
  );
}
