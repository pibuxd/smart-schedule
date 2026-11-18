import { Link } from "@tanstack/react-router";

import { useLocationInstructions } from "../../api/generated/assistant/assistant";
import { InlineError, Loading } from "../../components/ui/status";
import { CopyPreviousAgreements } from "./CopyPreviousAgreements";

/** The settings attached to the availability period, preserved after publication. */
export function AssistantRulesTable({
  locationId,
  periodId,
  compact = false,
}: {
  locationId: string;
  periodId?: string;
  compact?: boolean;
}) {
  const query = useLocationInstructions(
    locationId,
    periodId ? { period_id: periodId } : undefined,
  );
  if (query.isPending) return <Loading>Wczytuję ustalone zasady…</Loading>;
  if (query.isError)
    return (
      <InlineError>
        Nie udało się wczytać ustaleń asystenta.{" "}
        <button
          type="button"
          className="min-h-(--touch) underline"
          onClick={() => void query.refetch()}
        >
          Spróbuj ponownie
        </button>
      </InlineError>
    );
  if (query.data?.status !== 200) return null;
  const data = query.data.data;
  const rules = (data.rules ?? []).filter((rule) => !compact || rule.changed);
  return (
    <section
      className="grid gap-3 rounded-lg border border-line bg-surface p-4"
      aria-label="Ustalenia asystenta"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-lg font-semibold">
            {compact ? "Ustalenia z asystentem" : "Zasady tego okresu"}
          </h2>
          <p className="mt-1 mb-0 text-sm text-ink-muted">
            {data.period_label}
          </p>
        </div>
        {data.closed ? (
          <span className="text-sm text-ink-muted">
            Wykorzystane w opublikowanym grafiku
          </span>
        ) : (
          <Link
            to="/kierownik/lokal/$locationId/asystent"
            params={{ locationId }}
            search={{ periodId: data.period_id ?? undefined }}
            className="inline-flex min-h-(--touch) items-center font-semibold text-accent underline"
          >
            Ustal zasady w rozmowie
          </Link>
        )}
      </div>
      <p className="m-0 text-sm text-ink-muted">
        {data.closed
          ? "Te ustalenia pozostają przy tym okresie i obowiązują także przy jego korektach. Nie przejdą na następny okres."
          : data.period_requested
            ? "Dotyczą tylko tego okresu. Nowy okres zaczyna bez ustaleń."
            : "Jeszcze bez okresu. Przypiszesz je przyciskiem „Poproś o dyspozycje”."}
      </p>
      {!data.closed && (
        <CopyPreviousAgreements
          locationId={locationId}
          periodId={periodId}
          defaultOpen={
            data.items.length === 0 &&
            !(data.rules ?? []).some((rule) => rule.changed)
          }
        />
      )}
      {rules.length > 0 || data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">
              Zasady i polecenia o osobach — {data.period_label}
            </caption>
            <thead>
              <tr className="border-b border-line">
                <th className="py-2 pr-4">Zasada</th>
                <th className="py-2">Ustalenie</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.code} className="border-b border-grid align-top">
                  <th scope="row" className="py-3 pr-4 font-semibold">
                    {rule.label}
                    <span className="block text-xs font-normal text-ink-muted">
                      {rule.changed ? "Ustalone w rozmowie" : "Z zasad lokalu"}
                    </span>
                  </th>
                  <td className="py-3">
                    {rule.enabled
                      ? rule.is_hard
                        ? "Bez wyjątków"
                        : "Włączona"
                      : "Wyłączona"}
                    {rule.details && (
                      <span className="block">{rule.details}</span>
                    )}
                  </td>
                </tr>
              ))}
              {data.items.map((item, index) => (
                <tr key={item.id} className="border-b border-grid align-top">
                  <th scope="row" className="py-3 pr-4 font-semibold">
                    Polecenie o osobach {index + 1}
                  </th>
                  <td className="py-3">
                    {item.text}
                    {!item.active && (
                      <span className="block text-ink-muted">
                        Wskazane dni już minęły.
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="m-0 text-sm text-ink-muted">
          Nie ma jeszcze dodatkowych ustaleń.
        </p>
      )}
    </section>
  );
}
