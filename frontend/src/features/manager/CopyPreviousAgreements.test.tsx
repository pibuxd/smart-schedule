import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { mockApi, renderScreen } from "../../test/render";
import { CopyPreviousAgreements } from "./CopyPreviousAgreements";
import { AsManager } from "./test-utils";

afterEach(() => vi.unstubAllGlobals());

const offer = {
  period_label: "01.11.2026–30.11.2026",
  rules: [
    {
      code: "max_shifts_per_week",
      label: "Najwyżej tyle zmian w tygodniu",
      enabled: true,
      is_hard: false,
      details: "liczba zmian: 4",
      changed: true,
    },
  ],
  items: [{ id: "i1", text: "Ania i Kasia: osobno", active: true }],
};

const show = () =>
  renderScreen(
    <AsManager>
      <CopyPreviousAgreements locationId="l1" periodId="p2" />
    </AsManager>,
  );

it("copies only what the manager ticked and starts with nothing ticked", async () => {
  const calls = mockApi((method) => [200, method === "GET" ? offer : {}]);
  show();
  const person = await screen.findByLabelText("Ania i Kasia: osobno");
  const button = screen.getByRole("button", { name: "Skopiuj zaznaczone" });
  expect(person).not.toBeChecked();
  expect(screen.getByLabelText(/Najwyżej tyle zmian/)).not.toBeChecked();
  expect(button).toBeDisabled();
  fireEvent.click(person);
  fireEvent.click(button);
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST")).toBe(true),
  );
  const sent = calls.find((c) => c.method === "POST")!;
  expect(sent.url).toContain("/api/locations/l1/agreements/copy");
  expect(sent.body).toEqual({
    period_id: "p2",
    rule_codes: [],
    instruction_ids: ["i1"],
  });
});

it("stays hidden when the previous period has nothing to copy", async () => {
  const calls = mockApi(() => [
    200,
    { period_label: null, rules: [], items: [] },
  ]);
  show();
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(screen.queryByText(/Skopiuj z poprzedniego/)).not.toBeInTheDocument();
});
