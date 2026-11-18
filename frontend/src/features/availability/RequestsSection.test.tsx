import { fireEvent, screen, waitFor } from "@testing-library/react";
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
    expect(
      await screen.findByText("Kierownik przeczyta tę prośbę sam."),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
      understood: false,
    });
  });

  it("a request nobody interpreted simply goes to the manager", async () => {
    mockApi(() => [200, [request({ status: "needs_manager", summary: null })]]);
    renderScreen(
      <RequestsSection companyId="c1" periodId="p1" editable={false} />,
    );
    await openChat();
    expect(
      await screen.findByText("Kierownik przeczyta tę prośbę sam."),
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
      await screen.findByText(
        /Twoje wcześniejsze prośby oraz nazwy osób i zmian/,
      ),
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

  it("shows an informational answer without claiming it was sent to the manager", async () => {
    mockApi(() => [
      200,
      [
        request({
          status: "answered",
          summary: "W publikacji masz 120 godzin.",
        }),
      ],
    ]);
    renderScreen(<RequestsSection companyId="c1" periodId="p1" editable />);
    await openChat();
    expect(
      await screen.findByText("W publikacji masz 120 godzin."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Przekaż wiadomość, aby dodać ją do listy próśb kierownika/,
      ),
    ).toBeInTheDocument();
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
      await screen.findByRole("button", { name: "Przekaż kierownikowi" }),
    );
    expect(
      await screen.findByText("Kierownik przeczyta tę prośbę sam."),
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
  const field = await screen.findByLabelText("Twoja prośba");
  await waitFor(() => expect(field).toBeEnabled());
  fireEvent.change(field, { target: { value: "Wolę piątki rano" } });
  fireEvent.keyDown(field, { key: "Enter" });
  expect(calls.some((c) => c.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Wyślij prośbę" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST")).toBe(true),
  );
});

it("does not claim an out-of-scope request reached the manager or offer forwarding", async () => {
  mockApi(() => [
    200,
    [
      request({
        status: "rejected",
        summary: "Pomagam tylko ustalać preferencje.",
      }),
    ],
  ]);
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
  expect(
    screen.queryByRole("button", { name: "Przekaż kierownikowi" }),
  ).not.toBeInTheDocument();
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
