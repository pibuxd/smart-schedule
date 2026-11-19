import { useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Pencil, Trash2, Undo2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import {
  useDeleteInstruction,
  useLocationInstructions,
  useOrderLocationInstructions,
  useRevertAgreedRule,
} from '../../api/generated/assistant/assistant'
import type { AgreedRuleOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { Tag } from '../../components/ui/field'
import { InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { useAssistantDrawer } from './assistant-drawer'
import { OpenAssistantButton } from './AssistantDrawer'
import { useManager } from './ManagerContext'
import { CopyPreviousAgreements } from './CopyPreviousAgreements'

function RowButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex min-h-(--touch) min-w-(--touch) cursor-pointer items-center justify-center rounded-md text-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}

const ruleValue = (rule: AgreedRuleOut) =>
  [rule.enabled ? (rule.is_hard ? 'Bez wyjątków' : 'Włączona') : 'Wyłączona', rule.details].filter(Boolean).join(' · ')

/**
 * "Ustalenia": what the manager approved in the assistant chat for one availability period. Rules changed in the
 * chat can be reworded there or put back to the location's setting; instructions about people can be reordered
 * (higher = more important), reworded or removed. Kept read-only once the period's schedule is published.
 */
export function AssistantRulesTable({
  locationId,
  periodId,
  compact = false,
}: {
  locationId: string
  periodId?: string
  compact?: boolean
}) {
  const { readOnly } = useManager()
  const drawer = useAssistantDrawer()
  const queryClient = useQueryClient()
  const params = periodId ? { period_id: periodId } : undefined
  const query = useLocationInstructions(locationId, params)
  const done = { onSuccess: () => void queryClient.invalidateQueries() }
  const order = useOrderLocationInstructions()
  const remove = useDeleteInstruction()
  const revert = useRevertAgreedRule()
  // Removing or reverting takes a second tap: an agreement can cost a long chat to reach.
  const [confirming, setConfirming] = useState<string | null>(null)

  if (query.isPending) return <Loading>Wczytuję ustalenia…</Loading>
  if (query.isError)
    return (
      <InlineError>
        Nie udało się wczytać ustaleń.{' '}
        <button type="button" className="min-h-(--touch) cursor-pointer underline" onClick={() => void query.refetch()}>
          Spróbuj ponownie
        </button>
      </InlineError>
    )
  if (query.data?.status !== 200) return null
  const data = query.data.data
  const chatPeriod = data.period_id ?? periodId
  const agreed = data.rules.filter((rule) => rule.changed)
  const inherited = data.rules.filter((rule) => !rule.changed)
  const items = data.items
  const busy = readOnly || data.closed || order.isPending || remove.isPending || revert.isPending
  const canChat = !!drawer && data.assistant_enabled && !readOnly && !data.closed
  const reword = (text: string) => drawer?.openChat({ periodId: chatPeriod, text })
  const move = (from: number, to: number) => {
    const ids = items.map((item) => item.id)
    ids.splice(to, 0, ...ids.splice(from, 1))
    order.mutate({ locationId, data: { ids, period_id: periodId } }, done)
  }
  const failure = order.error ?? remove.error ?? revert.error
  const confirm = (question: string, yes: string, act: () => void) => (
    <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
      <span className="text-sm font-semibold">{question}</span>
      <Button
        variant="quiet"
        size="normal"
        disabled={busy}
        onClick={() => {
          setConfirming(null)
          act()
        }}
      >
        {yes}
      </Button>
      <Button variant="quiet" size="normal" onClick={() => setConfirming(null)}>
        Nie
      </Button>
    </span>
  )

  return (
    <section className="grid gap-3 rounded-lg border border-line bg-surface p-4" aria-label="Ustalenia z asystentem">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-lg font-semibold">Ustalenia z asystentem</h2>
          <p className="m-0 text-sm text-ink-muted">
            {data.closed
              ? `${data.period_label} · wykorzystane w opublikowanym grafiku`
              : data.period_requested
                ? `Na okres ${data.period_label}`
                : 'Czekają na prośbę o dyspozycje'}
          </p>
        </div>
        {!data.closed && !readOnly && <OpenAssistantButton periodId={chatPeriod}>Ustal w rozmowie</OpenAssistantButton>}
      </div>

      {!data.closed && (
        <CopyPreviousAgreements
          locationId={locationId}
          periodId={periodId}
          defaultOpen={items.length === 0 && agreed.length === 0}
        />
      )}

      {agreed.length === 0 && items.length === 0 && (
        <p className="m-0 text-sm text-ink-muted">
          {data.closed
            ? 'Na ten okres nic nie ustalono.'
            : 'Nic jeszcze nie ustalono. Zasada pojawi się tutaj, gdy zatwierdzisz ją w rozmowie z asystentem.'}
        </p>
      )}

      {(agreed.length > 0 || items.length > 0) && !data.closed && (
        <p className="m-0 text-sm text-ink-muted">
          Działają tylko w tym okresie i mają pierwszeństwo przed ustawieniem lokalu.
        </p>
      )}

      {agreed.length > 0 && (
        <div className="grid gap-1">
          <h3 className="m-0 text-sm font-semibold text-ink-muted">Zasady</h3>
          <ul className="m-0 grid list-none gap-2 p-0">
            {agreed.map((rule) => (
              <li
                key={rule.code}
                className="flex flex-wrap items-center gap-x-2 rounded-md border border-grid py-1 pr-1 pl-3"
              >
                <span className="min-w-0 flex-1 basis-40 py-2">
                  <span className="font-semibold">{rule.label}</span>
                  <span className="block text-sm text-ink-muted">{ruleValue(rule)}</span>
                </span>
                {!data.closed &&
                  (confirming === `rule:${rule.code}` ? (
                    confirm('Przywrócić obecne ustawienie lokalu?', 'Tak, przywróć', () =>
                      revert.mutate({ locationId, code: rule.code, params }, done),
                    )
                  ) : (
                    <span className="flex shrink-0">
                      {canChat && (
                        <RowButton
                          label={`Zmień: ${rule.label}`}
                          disabled={busy}
                          onClick={() => reword(`Zmień zasadę „${rule.label}”: `)}
                        >
                          <Pencil aria-hidden="true" size={18} />
                        </RowButton>
                      )}
                      <RowButton
                        label={`Przywróć obecne ustawienie lokalu: ${rule.label}`}
                        disabled={busy}
                        onClick={() => setConfirming(`rule:${rule.code}`)}
                      >
                        <Undo2 aria-hidden="true" size={18} />
                      </RowButton>
                    </span>
                  ))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {items.length > 0 && (
        <div className="grid gap-1">
          <h3 className="m-0 text-sm font-semibold text-ink-muted">
            Polecenia o osobach{items.length > 1 && ' · wyżej = ważniejsze'}
          </h3>
          <ol className="m-0 grid list-none gap-2 p-0">
            {items.map((item, index) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center gap-x-2 rounded-md border border-grid py-1 pr-1 pl-3"
              >
                <span className="font-extrabold tabular-nums">{index + 1}.</span>
                <span className="min-w-0 flex-1 basis-40 py-2">{item.text}</span>
                {!item.active && <Tag>minęło</Tag>}
                {!data.closed &&
                  (confirming === `item:${item.id}` ? (
                    confirm('Usunąć to polecenie?', 'Tak, usuń', () => remove.mutate({ instructionId: item.id }, done))
                  ) : (
                    <span className="ml-auto flex shrink-0">
                      {items.length > 1 && (
                        <>
                          <RowButton
                            label={`Wyżej: ${item.text}`}
                            disabled={busy || index === 0}
                            onClick={() => move(index, index - 1)}
                          >
                            <ArrowUp aria-hidden="true" size={18} />
                          </RowButton>
                          <RowButton
                            label={`Niżej: ${item.text}`}
                            disabled={busy || index === items.length - 1}
                            onClick={() => move(index, index + 1)}
                          >
                            <ArrowDown aria-hidden="true" size={18} />
                          </RowButton>
                        </>
                      )}
                      {canChat && (
                        <RowButton
                          label={`Zmień: ${item.text}`}
                          disabled={busy}
                          onClick={() => reword(`Zmień polecenie „${item.text}”: `)}
                        >
                          <Pencil aria-hidden="true" size={18} />
                        </RowButton>
                      )}
                      <RowButton
                        label={`Usuń: ${item.text}`}
                        disabled={busy}
                        onClick={() => setConfirming(`item:${item.id}`)}
                      >
                        <Trash2 aria-hidden="true" size={18} />
                      </RowButton>
                    </span>
                  ))}
              </li>
            ))}
          </ol>
        </div>
      )}

      {failure && <InlineError>{errorMessage(failure, NETWORK_PROBLEM)}</InlineError>}

      {!compact && inherited.length > 0 && (
        <details className="text-sm">
          <summary className="flex min-h-(--touch) cursor-pointer items-center text-ink-muted">
            Pozostałe zasady lokalu w tym okresie ({inherited.length})
          </summary>
          <ul className="mt-0 mb-1 grid list-none gap-1 p-0">
            {inherited.map((rule) => (
              <li key={rule.code}>
                <span className="font-semibold">{rule.label}</span>
                <span className="text-ink-muted"> · {ruleValue(rule)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
