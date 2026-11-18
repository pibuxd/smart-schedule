import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  useCopyPreviousAgreements,
  usePreviousAgreements,
} from "../../api/generated/assistant/assistant";
import { Button } from "../../components/ui/button";
import { InlineError } from "../../components/ui/status";
import { errorMessage, NETWORK_PROBLEM } from "../../lib/api-error";
import { useManager } from "./ManagerContext";

/** The manager ticks which agreements of the previous period to keep. Nothing is ticked or copied by default. */
export function CopyPreviousAgreements({
  locationId,
  periodId,
}: {
  locationId: string;
  periodId?: string;
}) {
  const { readOnly } = useManager();
  const queryClient = useQueryClient();
  const previous = usePreviousAgreements(
    locationId,
    periodId ? { period_id: periodId } : undefined,
  );
  const copy = useCopyPreviousAgreements();
  const [codes, setCodes] = useState<string[]>([]);
  const [ids, setIds] = useState<string[]>([]);
  const data = previous.data?.status === 200 ? previous.data.data : undefined;
  const rules = data?.rules ?? [];
  const items = data?.items ?? [];
  if (!data?.period_label || rules.length + items.length === 0) return null;
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  const chosen = codes.length + ids.length;
  return (
    <details className="rounded-md border border-line px-3 text-sm">
      <summary className="flex min-h-(--touch) cursor-pointer items-center font-semibold">
        Skopiuj z poprzedniego okresu ({rules.length + items.length})
      </summary>
      <form
        className="grid gap-2 pb-3"
        onSubmit={(event) => {
          event.preventDefault();
          copy.mutate(
            {
              locationId,
              data: {
                period_id: periodId ?? null,
                rule_codes: codes,
                instruction_ids: ids,
              },
            },
            {
              onSuccess: () => {
                setCodes([]);
                setIds([]);
                void queryClient.invalidateQueries();
              },
            },
          );
        }}
      >
        <p className="m-0 text-ink-muted">
          Ustalenia z okresu {data.period_label}. Zaznacz te, które mają
          obowiązywać także teraz.
        </p>
        <fieldset
          className="m-0 grid gap-1 border-0 p-0"
          disabled={readOnly || copy.isPending}
        >
          <legend className="sr-only">Ustalenia do skopiowania</legend>
          {rules.map((rule) => (
            <label
              key={rule.code}
              className="flex min-h-(--touch) cursor-pointer items-center gap-3"
            >
              <input
                type="checkbox"
                className="size-5 shrink-0"
                checked={codes.includes(rule.code)}
                onChange={() => setCodes(toggle(codes, rule.code))}
              />
              <span>
                {rule.label}:{" "}
                {rule.enabled
                  ? rule.is_hard
                    ? "bez wyjątków"
                    : "włączona"
                  : "wyłączona"}
                {rule.details && ` (${rule.details})`}
              </span>
            </label>
          ))}
          {items.map((item) => (
            <label
              key={item.id}
              className="flex min-h-(--touch) cursor-pointer items-center gap-3"
            >
              <input
                type="checkbox"
                className="size-5 shrink-0"
                checked={ids.includes(item.id)}
                onChange={() => setIds(toggle(ids, item.id))}
              />
              <span>{item.text}</span>
            </label>
          ))}
        </fieldset>
        {copy.isError && (
          <InlineError>{errorMessage(copy.error, NETWORK_PROBLEM)}</InlineError>
        )}
        <div>
          <Button
            type="submit"
            variant="secondary"
            size="normal"
            disabled={readOnly || copy.isPending || chosen === 0}
          >
            {copy.isPending ? "Kopiuję…" : "Skopiuj zaznaczone"}
          </Button>
        </div>
      </form>
    </details>
  );
}
