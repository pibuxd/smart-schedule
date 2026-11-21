import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AssistantCommandOut,
  InstructionsOut,
} from "../../api/generated/model";
import { mockApi, renderScreen } from "../../test/render";
import { AssistantPanel } from "./Assistant";
import { AsManager } from "./test-utils";

const command: AssistantCommandOut = {
  id: "cmd1",
  text: "Ania i Kasia nie razem",
  status: "ready",
  reply: "Proponuję osobne zmiany.",
  question: null,
  lines: ["Ania i Kasia: osobno, nie na tej samej zmianie."],
  effects: [],
  notes: [],
  can_apply: true,
  informational: false,
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  rule_set_id: "set1",
  period_label: "Grudzień 2026",
  consumed_at: null,
  has_hours: false,
  hours_only: false,
};
const instructions = (
  items: { id: string; text: string; active: boolean }[] = [],
  enabled = true,
): InstructionsOut => ({
  assistant_enabled: enabled,
  items,
  rule_set_id: "set1",
  period_id: "p1",
  period_label: "Grudzień 2026",
  period_requested: true,
  consumed_at: null,
  closed: false,
  rules: [],
});
const panel = (readOnly = false) =>
  renderScreen(
    <AsManager readOnly={readOnly}>
      <AssistantPanel locationId="l1" />
    </AsManager>,
  );

function chatApi(initial: AssistantCommandOut[] = []) {
  let rows = [...initial];
  const calls = mockApi((method, path, body) => {
    if (path.endsWith("/instructions")) return [200, instructions()];
    if (path === "/api/locations/l1/assistant-commands") {
      if (method === "GET") return [200, rows];
      const row = {
        ...command,
        id: `cmd${rows.length + 1}`,
        text: (body as { text: string }).text,
      };
      rows = [...rows, row];
      return [201, row];
    }
    if (path.endsWith("/apply") || path.endsWith("/dismiss")) {
      const id = path.split("/")[3];
      rows = rows.map((row) =>
        row.id === id
          ? {
              ...row,
              status: path.endsWith("/apply") ? "applied" : "dismissed",
              can_apply: false,
            }
          : row,
      );
      return [200, rows.find((row) => row.id === id)];
    }
    return [404, { detail: "Nie znaleziono." }];
  });
  return calls;
}

describe("Assistant chat", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("retains the message and proposal after acceptance, and does not apply before the click", async () => {
    const calls = chatApi();
    panel();
    fireEvent.change(await screen.findByLabelText("Twoja wiadomość"), {
      target: { value: command.text },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Wyślij wiadomość" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Wyślij wiadomość" }));
    expect(await screen.findByText(command.lines[0])).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Zatwierdź zmiany" }));
    expect(
      await screen.findByText(/Zapisane w ustaleniach/),
    ).toBeInTheDocument();
    expect(screen.getByText(command.text)).toBeInTheDocument();
    expect(screen.getByText(command.lines[0])).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zatwierdź zmiany" }),
    ).not.toBeInTheDocument();
  });

  it("loads prior replies and keeps successive messages after reopening", async () => {
    chatApi([
      {
        ...command,
        can_apply: false,
        informational: true,
        lines: [],
        reply: "Odpoczynek między zmianami określa minimalną przerwę.",
      },
    ]);
    const first = panel();
    expect(
      await screen.findByText(
        "Odpoczynek między zmianami określa minimalną przerwę.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Asystent może się pomylić/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Twoja wiadomość"), {
      target: { value: "A Kasia?" },
    });
    fireEvent.keyDown(screen.getByLabelText("Twoja wiadomość"), {
      key: "Enter",
    });
    expect(await screen.findByText("A Kasia?")).toBeInTheDocument();
    expect(
      screen.getByText("Odpoczynek między zmianami określa minimalną przerwę."),
    ).toBeInTheDocument();
    first.unmount();
    panel();
    expect(await screen.findByText("A Kasia?")).toBeInTheDocument();
    expect(
      screen.getByText("Odpoczynek między zmianami określa minimalną przerwę."),
    ).toBeInTheDocument();
  });

  it("prefills a suggestion without submitting it, and Shift+Enter does not send", async () => {
    const calls = chatApi();
    panel();
    const starter = await screen.findByRole("button", {
      name: "Ustal odpoczynek",
    });
    await waitFor(() => expect(starter).toBeEnabled());
    fireEvent.click(starter);
    const field = screen.getByLabelText("Twoja wiadomość");
    expect(field).toHaveValue(
      "Ustaw co najmniej 11 godzin odpoczynku między zmianami.",
    );
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("preserves the draft after a failed send", async () => {
    mockApi((method, path) =>
      method === "POST"
        ? [500, {}]
        : [200, path.endsWith("/instructions") ? instructions() : []],
    );
    panel();
    const field = await screen.findByLabelText("Twoja wiadomość");
    await waitFor(() => expect(field).toBeEnabled());
    fireEvent.change(field, { target: { value: "Moja ważna wiadomość" } });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij wiadomość" }));
    expect(
      await screen.findByText(/Tekst pozostał w polu wiadomości/),
    ).toBeInTheDocument();
    expect(field).toHaveValue("Moja ważna wiadomość");
  });

  it("keeps informational replies without approval or close buttons", async () => {
    chatApi([
      {
        ...command,
        reply: "Odpoczynek między zmianami określa minimalną przerwę.",
        lines: [],
        can_apply: false,
      },
    ]);
    panel();
    expect(
      await screen.findByText(
        "Odpoczynek między zmianami określa minimalną przerwę.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zatwierdź zmiany" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zamknij" }),
    ).not.toBeInTheDocument();
  });

  it("keeps rejected plans in the conversation", async () => {
    chatApi([command]);
    panel();
    fireEvent.click(await screen.findByRole("button", { name: "Odrzuć" }));
    expect(await screen.findByText(/Propozycja odrzucona/)).toBeInTheDocument();
    expect(screen.getByText(command.lines[0])).toBeInTheDocument();
  });

  it("disables posting and approvals in read-only mode", async () => {
    const calls = chatApi([command]);
    panel(true);
    expect(
      await screen.findByRole("button", { name: "Zatwierdź zmiany" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Odrzuć" })).toBeDisabled();
    expect(screen.getByLabelText("Twoja wiadomość")).toBeDisabled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("keeps history readable when the assistant is off", async () => {
    mockApi((_method, path) => [
      200,
      path.endsWith("/instructions") ? instructions([], false) : [command],
    ]);
    panel();
    expect(
      await screen.findByText(/Asystent jest wyłączony/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Twoja wiadomość")).toBeDisabled();
    expect(screen.getByText(command.text)).toBeInTheDocument();
  });

  it("offers a read retry for a delayed answer without resending the prompt", async () => {
    const calls = chatApi([
      {
        ...command,
        status: "queued",
        created_at: new Date(Date.now() - 100_000).toISOString(),
      },
    ]);
    panel();
    fireEvent.click(
      await screen.findByRole("button", { name: "Sprawdź odpowiedź" }),
    );
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    await waitFor(() =>
      expect(
        calls.filter((c) => c.url.endsWith("/assistant-commands")).length,
      ).toBeGreaterThan(1),
    );
  });
});

it("expires an old proposal and prefills its text without posting", async () => {
  const calls = chatApi([
    {
      ...command,
      expires_at: new Date(Date.now() - 1000).toISOString(),
      can_apply: false,
    },
  ]);
  panel();
  fireEvent.click(
    await screen.findByRole("button", { name: "Przygotuj ponownie" }),
  );
  expect(screen.getByLabelText("Twoja wiadomość")).toHaveValue(command.text);
  expect(
    screen.queryByRole("button", { name: "Zatwierdź zmiany" }),
  ).not.toBeInTheDocument();
  expect(calls.some((c) => c.method === "POST")).toBe(false);
});

it("marks only the last ten messages from the current period as remembered", async () => {
  chatApi([
    { ...command, id: "other", rule_set_id: "older-set" },
    // Older than a day: still remembered when among the last ten.
    ...Array.from({ length: 11 }, (_, i) => ({
      ...command,
      id: `recent-${i}`,
      created_at: new Date(Date.now() - (11 - i) * 86_400_000).toISOString(),
    })),
  ]);
  panel();
  // One line above the older messages, and the period said once instead of above every message.
  await waitFor(() =>
    expect(
      screen.getAllByText("Starsze wiadomości. Asystent ich nie pamięta."),
    ).toHaveLength(1),
  );
  expect(screen.getAllByText("Grudzień 2026")).toHaveLength(1);
  // The limit is explained only in the fold, not under the field.
  expect(
    screen.getByText(/Pamięta 10 ostatnich\s+wiadomości z tego okresu/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/Shift\+Enter|Możesz pisać/),
  ).not.toBeInTheDocument();
});

it("sends the explicitly selected period with a new command", async () => {
  const calls = chatApi();
  renderScreen(
    <AsManager>
      <AssistantPanel locationId="l1" periodId="p2" />
    </AsManager>,
  );
  const field = await screen.findByLabelText("Twoja wiadomość");
  await waitFor(() => expect(field).toBeEnabled());
  fireEvent.change(field, { target: { value: "Anna i Kasia osobno" } });
  fireEvent.click(screen.getByRole("button", { name: "Wyślij wiadomość" }));
  await waitFor(() =>
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      text: "Anna i Kasia osobno",
      period_id: "p2",
    }),
  );
  expect(calls.some((c) => c.url.includes("instructions?period_id=p2"))).toBe(
    true,
  );
});

it("labels an unaccepted proposal from a published period without approval actions", async () => {
  chatApi([
    { ...command, consumed_at: new Date().toISOString(), can_apply: false },
  ]);
  panel();
  expect(await screen.findByText("Okres zamknięty")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Zatwierdź zmiany" }),
  ).not.toBeInTheDocument();
});

it("keeps a plan of hours open after the period is published and says where the hours are", async () => {
  const calls = chatApi([
    {
      ...command,
      text: "Ewa wyszła dziś o 12",
      lines: ["Godziny osoby Ewa: sob. 21.11, 06:00–12:00 zamiast 06:00–14:00 (krócej o 2 h)."],
      consumed_at: new Date().toISOString(),
      has_hours: true,
      hours_only: true,
    },
  ]);
  panel();
  expect(await screen.findByText("Do zatwierdzenia")).toBeInTheDocument();
  expect(screen.queryByText("Okres zamknięty")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Zatwierdź zmiany" }));
  expect(
    await screen.findByText("Zapisane. Godziny liczą się od razu, zobaczysz je w „Godzinach”."),
  ).toBeInTheDocument();
  expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/cmd1/apply"))).toBe(true);
});
