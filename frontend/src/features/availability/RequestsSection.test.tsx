import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderScreen } from "../../test/render";
import { RequestsSection } from "./RequestsSection";

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
  unmarked_days: [],
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
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
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
    renderScreen(
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
    renderScreen(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    const reading = (await screen.findByText("Czytamy Twoją wiadomość…"))
      .closest("[role=status]") as HTMLElement;
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
                unmarked_days: ["2026-12-14", "2026-12-15"],
                notes: [
                  "W kalendarzu masz „Chętnie” w dni, w które prośba mówi o wolnym: 15.12.",
                ],
              }),
            ],
          ],
    );
    renderScreen(
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
          { date: "2026-12-14", state: "cannot" },
          { date: "2026-12-15", state: "cannot" },
        ],
      }),
    );
    expect(calls.find((c) => c.method === "PUT")!.url).toBe("/api/me/calendar");
  });

  it("a request nobody interpreted simply goes to the manager", async () => {
    mockApi(() => [200, [request({ status: "needs_manager", summary: null })]]);
    renderScreen(
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
    const { unmount } = renderScreen(
      <RequestsSection companyId="c1" periodId="p1" editable assistantReads />,
    );
    await openChat();
    expect(
      await screen.findByText(/sprawdza to, co widzisz w aplikacji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Przeczyta to tylko kierownik/),
    ).not.toBeInTheDocument();
    unmount();

    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
    await openChat();
    expect(
      await screen.findByText(/Przeczyta to tylko kierownik/),
    ).toBeInTheDocument();
  });

  it("keeps superseded requests visible without an edit action", async () => {
    mockApi(() => [200, [request({ status: "superseded", summary: null })]]);
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
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
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
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

  it("lets the employee forward a misclassified question to the manager", async () => {
    let row = request({ status: "answered", summary: "Odpowiedź asystenta." });
    const calls = mockApi((method) => {
      if (method === "PATCH") {
        row = request({ status: "needs_manager", summary: null });
        return [200, row];
      }
      return [200, [row]];
    });
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
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
  renderScreen(
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
  renderScreen(
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
    renderScreen(
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
    renderScreen(
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
    renderScreen(
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
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
    fireEvent.click(await screen.findByRole("button", { name: "Usuń prośbę" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Tak, usuń" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE")).toBe(true),
    );
  });

  it("offers no edits once the period is closed", async () => {
    mockApi(() => [200, [request()]]);
    renderScreen(
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
    renderScreen(
      <RequestsSection companyId="c1" month="2026-11-01" editable assistantReads />,
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
      calls.find((c) => c.method === "POST" && c.url === "/api/me/hours-changes")!
        .body,
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
    renderScreen(
      <RequestsSection companyId="c1" month="2026-11-01" editable assistantReads />,
    );
    await openChat();
    expect(
      await screen.findByText(/nie masz już tej zmiany, więc tego zgłoszenia nie wyślesz/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Kierownik zatwierdził te godziny."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Wyślij kierownikowi" }),
    ).not.toBeInTheDocument();
  });
});
