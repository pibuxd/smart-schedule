import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps, ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi as mockAnswers, renderScreen } from "../../test/render";
import { EmployeeChatProvider } from "./EmployeeChat";
import { RequestsSection } from "./RequestsSection";

// The chat lives in the employee layout and asks the server whether the assistant reads messages.
let assistantReads = false;
const mockApi: typeof mockAnswers = (answer) =>
  mockAnswers((method, path, body) =>
    path === "/api/me/availability"
      ? [
          200,
          {
            period: null,
            days: [],
            submitted_at: null,
            assistant_reads: assistantReads,
          },
        ]
      : answer(method, path, body),
  );

/** "Twoje prośby" with the chat around it, as in the employee layout. */
function renderSection(
  ui: ReactElement<ComponentProps<typeof RequestsSection>>,
) {
  assistantReads = ui.props.assistantReads ?? false;
  return renderScreen(
    <EmployeeChatProvider companyId={ui.props.companyId} readOnly={false}>
      {ui}
    </EmployeeChatProvider>,
  );
}

const openChat = async () =>
  fireEvent.click(
    await screen.findByRole("button", {
      name: /Napisz do asystenta|Napisz prośbę|Pokaż rozmowę/,
    }),
  );

const request = (over = {}) => ({
  id: "r1",
  text: "Wolałabym nie pracować w piątki.",
  status: "interpreted",
  summary: "Wolne w piątki, jeśli się da.",
  reply: null,
  cannot_marks: [],
  notes: [],
  created_at: "2026-11-01T10:00:00Z",
  ...over,
});

describe("RequestsSection", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows how the request was understood and lets the person say it is wrong", async () => {
    let rows = [request()];
    const calls = mockApi((method) => {
      if (method === "PATCH") {
        rows = [request({ status: "needs_manager", summary: null })];
        return [200, rows[0]];
      }
      return [200, rows];
    });
    renderSection(<RequestsSection companyId="c1" periodId="p1" editable />);
    expect(
      await screen.findByText("Wolne w piątki, jeśli się da."),
    ).toBeInTheDocument();

    await openChat();
    fireEvent.click(
      screen.getByRole("button", { name: "Nie o to mi chodziło" }),
    );
    // First a chance to write it again; handing it to the manager is the second choice.
    expect(screen.getByLabelText("Napisz to inaczej")).toHaveValue(
      "Wolałabym nie pracować w piątki.",
    );
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Niech przeczyta kierownik" }),
    );
    expect(
      await screen.findByText(/Kierownik przeczyta tę prośbę sam/),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
      understood: false,
    });
  });

  it("lets the person write a misunderstood request again", async () => {
    const calls = mockApi((method) =>
      method === "PATCH"
        ? [200, request({ status: "new", summary: null })]
        : [200, [request()]],
    );
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    fireEvent.click(
      await screen.findByRole("button", { name: "Nie o to mi chodziło" }),
    );
    fireEvent.change(screen.getByLabelText("Napisz to inaczej"), {
      target: { value: "Wolne tylko w piątki po południu." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij poprawioną" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
        text: "Wolne tylko w piątki po południu.",
      }),
    );
  });

  it("shows a reading robot while the assistant reads a message", async () => {
    mockApi(() => [200, [request({ status: "new", summary: null })]]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    const reading = (
      await screen.findByText("Myślę…")
    ).closest("[role=status]") as HTMLElement;
    expect(within(reading).getByTestId("reading-robot")).toBeInTheDocument();
  });

  it("offers to mark the days the person cannot work and shows calendar notes", async () => {
    const calls = mockApi((method) =>
      method === "PUT"
        ? [204, null]
        : [
            200,
            [
              request({
                reply: "Powodzenia na sesji.",
                summary: "Wolne 14.12–16.12 („nie mogę”).",
                cannot_marks: [{ days: ["2026-12-14", "2026-12-15"] }],
                notes: [
                  "W kalendarzu masz „Chętnie” w dni, w które prośba mówi o wolnym: 15.12.",
                ],
              }),
            ],
          ],
    );
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    expect(await screen.findByText("Powodzenia na sesji.")).toBeInTheDocument();
    expect(screen.getByText(/masz „Chętnie”/)).toBeInTheDocument();
    expect(
      screen.getByText(/nadal do pracy: 14.12, 15.12/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zaznacz „nie mogę”" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
        company_id: "c1",
        days: [
          { date: "2026-12-14", state: "cannot", from_time: null, to_time: null },
          { date: "2026-12-15", state: "cannot", from_time: null, to_time: null },
        ],
      }),
    );
    expect(calls.find((c) => c.method === "PUT")!.url).toBe("/api/me/calendar");
  });

  it("marks only the hours the person cannot work and can narrow whole days to them", async () => {
    // "We wtorki nie mogę od 9:00 do 11:00": the rest of those days stays open to work.
    const calls = mockApi((method) =>
      method === "PUT"
        ? [204, null]
        : [
            200,
            [
              request({
                summary: "Wolne 1.12, 8.12 tylko w godz. 9:00–11:00 („nie mogę”).",
                cannot_marks: [
                  { days: ["2026-12-01"], from_time: "09:00", to_time: "11:00", whole_day: true },
                  { days: ["2026-12-08"], from_time: "09:00", to_time: "11:00", whole_day: false },
                ],
              }),
            ],
          ],
    );
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    expect(
      await screen.findByText(/mają „Nie mogę” przez cały dzień, a prośba mówi tylko o godzinach 9:00–11:00: 1.12/),
    ).toBeInTheDocument();
    expect(screen.getByText(/nadal do pracy w godzinach 9:00–11:00: 8.12/)).toBeInTheDocument();
    // Narrowing a whole day says what it costs: the rest of the day can get a shift.
    expect(screen.getByText(/możesz dostać zmianę w pozostałych godzinach tych dni/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zmień na „nie mogę” 9:00–11:00" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
        company_id: "c1",
        days: [{ date: "2026-12-01", state: "cannot", from_time: "09:00", to_time: "11:00" }],
      }),
    );
    expect(screen.getByRole("button", { name: "Zaznacz „nie mogę” 9:00–11:00" })).toBeInTheDocument();
  });

  it("a request nobody interpreted simply goes to the manager", async () => {
    mockApi(() => [200, [request({ status: "needs_manager", summary: null })]]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable={false} />,
    );
    await openChat();
    expect(
      await screen.findByText(/Kierownik przeczyta tę prośbę sam/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Tak to zrozumieliśmy/)).not.toBeInTheDocument();
  });

  it("says that the assistant also reads the request, only when it does", async () => {
    mockApi(() => [200, []]);
    const { unmount } = renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    expect(
      await screen.findByText(/sprawdza to, co widzisz w aplikacji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Przeczyta to tylko kierownik/),
    ).not.toBeInTheDocument();
    // Piotr, 23.11.2026: no line under the field about who reads the chat; the manager sees requests, not the chat.
    expect(screen.queryByText(/Czyta to/)).not.toBeInTheDocument();
    expect(screen.getByText(/Reszty rozmowy nie widzą/)).toBeInTheDocument();
    unmount();

    renderSection(<RequestsSection companyId="c1" periodId="p1" editable />);
    await openChat();
    expect(
      await screen.findByText(/Przeczyta to tylko kierownik/),
    ).toBeInTheDocument();
  });

  it("keeps superseded requests visible without an edit action", async () => {
    mockApi(() => [200, [request({ status: "superseded", summary: null })]]);
    renderSection(<RequestsSection companyId="c1" periodId="p1" editable />);
    await openChat();
    expect(
      await screen.findByText(/Ta prośba została zastąpiona/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edytuj prośbę" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Nie o to mi chodziło" }),
    ).not.toBeInTheDocument();
  });

  it("shows an answer without claiming it was sent to the manager", async () => {
    mockApi(() => [
      200,
      [
        request({
          status: "answered",
          summary: null,
          reply: "W listopadzie masz 120 godzin.",
        }),
        request({
          id: "old",
          status: "answered",
          summary: "Starsza odpowiedź zapisana jako opis.",
        }),
      ],
    ]);
    renderSection(<RequestsSection companyId="c1" periodId="p1" editable />);
    await openChat();
    expect(
      await screen.findByText("W listopadzie masz 120 godzin."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Starsza odpowiedź zapisana jako opis."),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Niech przeczyta kierownik" }),
    ).toHaveLength(2);
    expect(screen.queryByText(/Asystent może się pomylić/)).toBeNull();
    expect(
      screen.queryByText("Zapisane w Twoich prośbach"),
    ).not.toBeInTheDocument();
  });

  it("shows the assistant's question and asks for an answer in the field", async () => {
    mockApi(() => [
      200,
      [
        request({
          text: "Chcę mniej pracować.",
          status: "answered",
          summary: null,
          question: "Ile najwyżej godzin w tygodniu chcesz pracować?",
          waiting: true,
          can_answer: true,
        }),
      ],
    ]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    // "Twoje prośby" says it is not saved yet, so it is not lost quietly.
    const waiting = await screen.findByRole("list", {
      name: "Czekają na Twoją odpowiedź",
    });
    expect(
      within(waiting).getByText(
        "Nie jest zapisana. Asystent pyta: Ile najwyżej godzin w tygodniu chcesz pracować?",
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(waiting).getByRole("button", { name: "Odpowiedz" }));
    expect(
      await screen.findByText(
        "Ile najwyżej godzin w tygodniu chcesz pracować?",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Asystent dopytuje")).toBeInTheDocument();
    expect(
      screen.getByText("Odpowiedz niżej. Do tego czasu niczego nie zapisuję."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Twoja wiadomość")).toHaveAttribute(
      "placeholder",
      "Odpowiedz asystentowi…",
    );
    // Not saved until the answer: nothing in "Twoje prośby".
    expect(screen.queryByRole("list", { name: "Zapisane prośby" })).toBeNull();
  });

  it("shows the earlier messages of a request the assistant asks about again", async () => {
    mockApi(() => [
      200,
      [
        request({
          id: "q2",
          text: "Trochę mniej.",
          status: "answered",
          summary: null,
          question: "Ile najwyżej w tygodniu?",
          waiting: true,
          can_answer: true,
          exchange: [{ text: "Chcę mniej pracować.", question: "Ile godzin?" }],
        }),
      ],
    ]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    const waiting = await screen.findByRole("list", {
      name: "Czekają na Twoją odpowiedź",
    });
    expect(waiting).toHaveTextContent(
      "Chcę mniej pracować.Trochę mniej.Nie jest zapisana. Asystent pyta: Ile najwyżej w tygodniu?",
    );
  });

  it("lets a question the assistant no longer remembers be written again", async () => {
    const calls = mockApi((method) =>
      method === "PATCH"
        ? [200, request({ status: "new", summary: null })]
        : [
            200,
            [
              request({
                id: "q",
                text: "Chcę mniej pracować.",
                status: "answered",
                summary: null,
                question: "Ile godzin?",
                waiting: true,
              }),
              request({ id: "later", created_at: "2026-11-02T10:00:00Z" }),
            ],
          ],
    );
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    const waiting = await screen.findByRole("list", {
      name: "Czekają na Twoją odpowiedź",
    });
    // Older than the assistant remembers: the chat would not take the next message as its answer.
    expect(
      within(waiting).queryByRole("button", { name: "Odpowiedz" }),
    ).toBeNull();
    fireEvent.click(
      within(waiting).getByRole("button", { name: "Napisz ją od nowa" }),
    );
    fireEvent.change(screen.getByLabelText("Treść prośby"), {
      target: { value: "Najwyżej 30 godzin w tygodniu." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz prośbę" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
        text: "Najwyżej 30 godzin w tygodniu.",
      }),
    );
    expect(calls.find((c) => c.method === "PATCH")!.url).toContain(
      "/api/me/requests/q",
    );
  });

  it("lets the employee forward a misclassified question to the manager", async () => {
    let row = request({ status: "answered", summary: "Odpowiedź asystenta." });
    const calls = mockApi((method) => {
      if (method === "PATCH") {
        row = request({ status: "needs_manager", summary: null });
        return [200, row];
      }
      return [200, [row]];
    });
    renderSection(<RequestsSection companyId="c1" periodId="p1" editable />);
    await openChat();
    fireEvent.click(
      await screen.findByRole("button", { name: "Niech przeczyta kierownik" }),
    );
    expect(
      await screen.findByText(/Kierownik przeczyta tę prośbę sam/),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
      understood: false,
    });
  });
});

it("does not send an employee request on Enter", async () => {
  const calls = mockApi(() => [200, []]);
  renderSection(
    <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
  );
  await openChat();
  const field = await screen.findByLabelText("Twoja wiadomość");
  await waitFor(() => expect(field).toBeEnabled());
  fireEvent.change(field, { target: { value: "Wolę piątki rano" } });
  fireEvent.keyDown(field, { key: "Enter" });
  expect(calls.some((c) => c.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST")).toBe(true),
  );
});

it("lets the employee forward a rejected request to the manager without claiming it was sent", async () => {
  const calls = mockApi((method) =>
    method === "PATCH"
      ? [200, request({ status: "needs_manager", summary: null })]
      : [
          200,
          [
            request({
              status: "rejected",
              summary: "Pomagam tylko ustalać preferencje.",
            }),
          ],
        ],
  );
  renderSection(
    <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
  );
  await openChat();
  expect(
    await screen.findByText("Pomagam tylko ustalać preferencje."),
  ).toBeInTheDocument();
  expect(screen.getByText("Odrzucona")).toBeInTheDocument();
  expect(
    screen.queryByText("Zapisane w Twoich prośbach"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Wysłane do kierownika")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Przekaż kierownikowi" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "PATCH")).toBe(true),
  );
  expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
    understood: false,
  });
});

describe("Twoje prośby window", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists only understood and forwarded requests, outside the chat", async () => {
    mockApi(() => [
      200,
      [
        request(),
        request({
          id: "r2",
          text: "Ile mam godzin?",
          status: "answered",
          summary: "Masz 120 godzin.",
        }),
        request({
          id: "r3",
          text: "Kup mi kawę",
          status: "rejected",
          summary: "Pomagam tylko z grafikiem.",
        }),
        request({
          id: "r4",
          text: "Potrzebuję wolnej soboty.",
          status: "needs_manager",
          summary: null,
        }),
      ],
    ]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    const saved = await screen.findByRole("list", { name: "Zapisane prośby" });
    expect(saved).toHaveTextContent("Wolne w piątki, jeśli się da.");
    expect(saved).toHaveTextContent("Potrzebuję wolnej soboty.");
    expect(saved).not.toHaveTextContent("Masz 120 godzin.");
    expect(saved).not.toHaveTextContent("Kup mi kawę");
    expect(screen.queryByRole("log")).not.toBeInTheDocument();
    expect(screen.queryByText(/nie jest prośbą/)).not.toBeInTheDocument();
  });

  it("leaves a trace in the window when the newest message was rejected", async () => {
    mockApi(() => [
      200,
      [
        request(),
        request({
          id: "r3",
          text: "Kup mi kawę",
          status: "rejected",
          summary: "Pomagam tylko z grafikiem.",
        }),
      ],
    ]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    expect(
      await screen.findByText(/została odrzucona i nie jest prośbą/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż odpowiedź" }));
    expect(
      await screen.findByText("Pomagam tylko z grafikiem."),
    ).toBeInTheDocument();
  });

  it("edits a saved request in the window", async () => {
    const calls = mockApi((method) =>
      method === "PATCH" ? [200, request()] : [200, [request()]],
    );
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Edytuj prośbę" }),
    );
    fireEvent.change(screen.getByLabelText("Treść prośby"), {
      target: { value: "Wolę piątki rano." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz prośbę" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PATCH")).toBe(true),
    );
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
      text: "Wolę piątki rano.",
    });
  });

  it("removes a saved request after a confirmation", async () => {
    const calls = mockApi((method) =>
      method === "DELETE" ? [204, null] : [200, [request()]],
    );
    renderSection(<RequestsSection companyId="c1" periodId="p1" editable />);
    fireEvent.click(await screen.findByRole("button", { name: "Usuń prośbę" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Tak, usuń" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE")).toBe(true),
    );
  });

  it("offers no edits once the period is closed", async () => {
    mockApi(() => [200, [request()]]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" editable={false} />,
    );
    expect(
      await screen.findByText("Wolne w piątki, jeśli się da."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edytuj prośbę" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Usuń prośbę" }),
    ).not.toBeInTheDocument();
  });
});

describe("reports of other hours in the chat", () => {
  afterEach(() => vi.unstubAllGlobals());

  const proposal = (over = {}) => ({
    assignment_id: "as1",
    date: "2026-11-20",
    start_time: "06:00",
    end_time: "11:00",
    planned_start_time: "06:00",
    planned_end_time: "14:00",
    difference_minutes: -180,
    location_name: "Rynek",
    position_name: "Sprzedawca",
    reason: "źle się czuję",
    sent_status: null,
    ...over,
  });

  it("sends a prepared report only when the person presses the button", async () => {
    let sent = false;
    const calls = mockApi((method, path) => {
      if (method === "POST" && path === "/api/me/hours-changes") {
        sent = true;
        return [201, { id: "h1", status: "pending" }];
      }
      return [
        200,
        [
          request({
            text: "Źle się czuję, wyjdę o 11.",
            status: "answered",
            summary: null,
            reply: "Przygotowałem zgłoszenie innych godzin.",
            hours_reports: [proposal(sent ? { sent_status: "pending" } : {})],
          }),
        ],
      ];
    });
    renderSection(
      <RequestsSection
        companyId="c1"
        month="2026-11-01"
        editable
        assistantReads
      />,
    );
    await openChat();
    const card = await screen.findByRole("list", {
      name: "Zgłoszenia innych godzin",
    });
    expect(card).toHaveTextContent(
      "piątek 20 listopada: 6:00–11:00 zamiast 6:00–14:00 (krócej o 3 h)",
    );
    expect(card).toHaveTextContent("Powód: źle się czuję");
    expect(calls.some((c) => c.method === "POST")).toBe(false); // nothing goes by itself

    fireEvent.click(
      within(card).getByRole("button", { name: "Wyślij kierownikowi" }),
    );

    expect(
      await within(card).findByText("Wysłane. Czeka na kierownika."),
    ).toBeInTheDocument();
    expect(
      calls.find(
        (c) => c.method === "POST" && c.url === "/api/me/hours-changes",
      )!.body,
    ).toEqual({
      assignment_id: "as1",
      start_time: "06:00",
      end_time: "11:00",
      reason: "źle się czuję",
      request_id: "r1",
    });
  });

  it("says when the shift is gone or the manager decided", async () => {
    mockApi(() => [
      200,
      [
        request({
          status: "answered",
          summary: null,
          reply: "Gotowe.",
          hours_reports: [
            proposal({ assignment_id: null }),
            proposal({ date: "2026-11-19", sent_status: "approved" }),
          ],
        }),
      ],
    ]);
    renderSection(
      <RequestsSection
        companyId="c1"
        month="2026-11-01"
        editable
        assistantReads
      />,
    );
    await openChat();
    expect(
      await screen.findByText(
        /nie masz już tej zmiany, więc tego zgłoszenia nie wyślesz/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Kierownik zatwierdził te godziny."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Wyślij kierownikowi" }),
    ).not.toBeInTheDocument();
  });
});

describe("requests that last", () => {
  afterEach(() => vi.unstubAllGlobals());
  const span = { start: "2027-01-01", end: "2027-01-31" };

  it("switches a saved request between this month only and lasting", async () => {
    const calls = mockApi((method, _path, body) =>
      method === "PATCH"
        ? [200, request({ can_last: true, ...(body as object) })]
        : [200, [request({ can_last: true, lasting: false })]],
    );
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" span={span} editable />,
    );
    const only = await screen.findByRole("button", {
      name: "Tylko w styczniu",
    });
    expect(only).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Na stałe" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
        lasting: true,
      }),
    );
  });

  it("offers no choice for a request about concrete days", async () => {
    mockApi(() => [200, [request({ can_last: false })]]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" span={span} editable />,
    );
    expect(
      await screen.findByText("Wolne w piątki, jeśli się da."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Na stałe" }),
    ).not.toBeInTheDocument();
  });

  it("lists a lasting request from an earlier month and ends it from this one", async () => {
    const carried = { lasting: true, carried_from: "2026-12-01" };
    let rows = [request(carried)];
    const calls = mockApi((method) => {
      if (method === "POST") {
        rows = [
          request({
            ...carried,
            ended: true,
            ended_by: "employee",
            ends_from: "2027-01-01",
          }),
        ];
        return [200, rows[0]];
      }
      return [200, rows];
    });
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" span={span} editable />,
    );
    expect(
      await screen.findByText(/Na stałe od grudnia\. Asystent zrozumiał/),
    ).toBeInTheDocument();
    // It belongs to December: here it can only be ended, not edited or removed.
    expect(
      screen.queryByRole("button", { name: "Edytuj prośbę" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zakończ" }));
    expect(screen.getByText("Zakończyć od stycznia?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tak, zakończ" }));
    expect(
      await screen.findByText("Zakończona: nie obowiązuje od stycznia."),
    ).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toContain("/api/me/requests/r1/end");
    expect(post.body).toEqual({
      company_id: "c1",
      period_id: "p1",
      ended: true,
    });
    expect(
      screen.getByRole("button", { name: "Przywróć" }),
    ).toBeInTheDocument();
  });

  it("does not bring back a request the manager ended", async () => {
    mockApi(() => [
      200,
      [
        request({
          lasting: true,
          carried_from: "2026-12-01",
          ended: true,
          ended_by: "manager",
          ends_from: "2027-01-01",
        }),
      ],
    ]);
    renderSection(
      <RequestsSection companyId="c1" periodId="p1" span={span} editable />,
    );
    expect(
      await screen.findByText(/Zakończył ją kierownik\./),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Przywróć" }),
    ).not.toBeInTheDocument();
  });

  it("keeps lasting requests from earlier months out of this month's chat", async () => {
    mockApi(() => [
      200,
      [
        request({
          id: "old",
          text: "Nie z Zuzanną.",
          lasting: true,
          carried_from: "2026-12-01",
        }),
        request({ id: "new", text: "Wolę ranne zmiany." }),
      ],
    ]);
    renderSection(
      <RequestsSection
        companyId="c1"
        periodId="p1"
        span={span}
        editable
        assistantReads
      />,
    );
    await openChat();
    const chat = await screen.findByRole("log");
    expect(within(chat).getByText("Wolę ranne zmiany.")).toBeInTheDocument();
    expect(within(chat).queryByText("Nie z Zuzanną.")).not.toBeInTheDocument();
  });
});
