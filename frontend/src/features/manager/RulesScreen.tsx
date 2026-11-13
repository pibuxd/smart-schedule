import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, GripVertical } from 'lucide-react'
import { useState } from 'react'

import type { PreviewOut, RuleItemIn, RuleItemOut, RulesOut } from '../../api/generated/model'
import { usePreviewScopeRules, useSaveScopeRules, useScopeRules } from '../../api/generated/rules/rules'
import { Button } from '../../components/ui/button'
import { CheckField, inputClass, Tag } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { cn } from '../../lib/cn'
import { AssistantPanel } from './Assistant'
import { useManager } from './ManagerContext'

type Scope = 'location' | 'group'
type Item = RuleItemOut

// Parameters that point at a location's positions or shift types: a group list does not show them.
const LOCATION_PARAMS = new Set(['position', 'shift_type'])

const PARAM_LABEL: Record<string, string> = {
  hours: 'Godzin przerwy co najmniej',
  days: 'Dni z rzędu najwyżej',
  shifts: 'Zmian w tygodniu najwyżej',
  max_hours: 'Godzin w ciągu dnia najwyżej',
  rest_hours: 'Godzin wolnego bez przerwy co najmniej',
  count: 'Ile osób co najmniej',
  position: 'Stanowisko',
  shift_type: 'Zmiana',
}

const toPayload = (items: Item[]): RuleItemIn[] =>
  items.map(({ code, enabled, is_hard, params }) => ({ code, enabled, is_hard, params }))

/**
 * One list of rules: the order is the importance (drag, or the arrows), a switch for each, "bez wyjątków" for the
 * ones that must never be broken. Before saving, the manager sees what the change would mean on the last schedule.
 */
export function RulesScreen({ scope, scopeId }: { scope: Scope; scopeId: string }) {
  const rules = useScopeRules(scope, scopeId)
  if (rules.isPending) return <Loading>Wczytuję zasady…</Loading>
  if (rules.isError) {
    return (
      <ErrorState onRetry={() => void rules.refetch()}>
        {errorMessage(rules.error, 'Nie udało się wczytać zasad. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = rules.data.data as RulesOut
  return <RulesEditor key={JSON.stringify(data.items)} data={data} scope={scope} scopeId={scopeId} />
}

function RulesEditor({ data, scope, scopeId }: { data: RulesOut; scope: Scope; scopeId: string }) {
  const { readOnly } = useManager()
  const [items, setItems] = useState<Item[]>(data.items)
  const [checking, setChecking] = useState(false)
  const preview = usePreviewScopeRules()
  const save = useSaveScopeRules()
  const queryClient = useQueryClient()
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const dirty = JSON.stringify(toPayload(items)) !== JSON.stringify(toPayload(data.items))

  const change = (code: string, patch: Partial<Item>) =>
    setItems((now) => now.map((i) => (i.code === code ? { ...i, ...patch } : i)))
  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length) return
    setItems((now) => arrayMove(now, from, to))
  }
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const from = items.findIndex((i) => i.code === active.id)
    const to = items.findIndex((i) => i.code === over.id)
    move(from, to)
  }
  const check = () => {
    setChecking(true)
    preview.mutate({ scope, scopeId, data: { items: toPayload(items) } })
  }
  const confirm = () =>
    save.mutate(
      { scope, scopeId, data: { items: toPayload(items) } },
      {
        onSuccess: () => {
          setChecking(false)
          void queryClient.invalidateQueries()
        },
      },
    )

  const result = preview.data?.data as PreviewOut | undefined
  let place = 0

  return (
    <div className="grid gap-5">
      {scope === 'location' && <AssistantPanel locationId={scopeId} />}
      <div className="grid gap-2">
        <h2 className="m-0 text-xl font-extrabold">
          {scope === 'group' ? `Zasady wspólne: ${data.name}` : 'Zasady lokalu'}
        </h2>
        <p className="m-0 max-w-[75ch] text-ink-muted">
          Wyżej na liście = ważniejsza. Gdy dwóch zasad nie da się spełnić naraz, wygrywa ta wyżej. „Bez wyjątków”
          zaznaczaj tylko tam, gdzie złamanie zasady jest gorsze niż nieobsadzona zmiana.
        </p>
        {scope === 'location' && data.group && (
          <p className="m-0 max-w-[75ch] text-ink-muted">
            Zasady z grupy „{data.group.name}” obowiązują też tutaj. Zmiana w tym lokalu dotyczy tylko jego. Gdy przesuniesz
            zasadę albo zmienisz jej ustawienie, ta zasada przestaje iść za grupą (etykieta „zmienione w tym lokalu”).
            Zasady ustawione dokładnie jak w grupie dalej zmieniają się razem z grupą.
          </p>
        )}
        {scope === 'group' && (
          <p className="m-0 max-w-[75ch] text-ink-muted">
            Te zasady obowiązują we wszystkich lokalach grupy. Każdy lokal może je u siebie zmienić albo wyłączyć.
          </p>
        )}
        <p className="m-0 max-w-[75ch] text-sm text-ink-muted">
          Grafikomat nie sprawdza Kodeksu pracy i za zgodność grafiku z prawem odpowiadasz Ty. Czasu pracy pilnują
          zasady „Odpoczynek między zmianami”, „Godziny pracy w ciągu dnia” i „Wolne w tygodniu”: są włączone, ale
          można je złamać, gdy brakuje ludzi. Zaznacz „Bez wyjątków”, żeby nigdy ich nie łamać. Dotyczą wszystkich osób
          w lokalu.
        </p>
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={items.map((i) => i.code)} strategy={verticalListSortingStrategy}>
          <ol className="m-0 grid list-none gap-2 p-0">
            {items.map((item, index) => {
              if (item.enabled) place += 1
              return (
                <RuleCard
                  key={item.code}
                  item={item}
                  place={item.enabled ? place : null}
                  index={index}
                  last={index === items.length - 1}
                  scope={scope}
                  data={data}
                  disabled={readOnly}
                  onChange={(patch) => change(item.code, patch)}
                  onMove={move}
                />
              )
            })}
          </ol>
        </SortableContext>
      </DndContext>

      <div
        className={cn(
          '-mx-4 flex flex-wrap items-center gap-3 border-t border-line bg-paper px-4 py-3',
          dirty && 'sticky bottom-0 z-20 shadow-sheet',
        )}
      >
        <Button onClick={check} disabled={!dirty || readOnly || preview.isPending}>
          Sprawdź skutek i zapisz
        </Button>
        <Button variant="quiet" size="normal" disabled={!dirty} onClick={() => setItems(data.items)}>
          Cofnij zmiany
        </Button>
        {!dirty && <span className="text-ink-muted">Brak niezapisanych zmian.</span>}
      </div>

      <Sheet open={checking} onOpenChange={setChecking} title="Co się zmieni?">
        <div className="grid gap-4">
          {preview.isPending && <Loading>Sprawdzam ostatni grafik…</Loading>}
          {preview.isError && <InlineError>{errorMessage(preview.error, NETWORK_PROBLEM)}</InlineError>}
          {result && <PreviewText result={result} />}
          {save.isError && <InlineError>{errorMessage(save.error, NETWORK_PROBLEM)}</InlineError>}
          <Button wide onClick={confirm} disabled={save.isPending || preview.isPending || preview.isError}>
            Zapisz zasady
          </Button>
          <Button variant="secondary" wide onClick={() => setChecking(false)}>
            Wróć do listy
          </Button>
        </div>
      </Sheet>
    </div>
  )
}

function PreviewText({ result }: { result: PreviewOut }) {
  if (!result.period) {
    return (
      <p className="m-0">
        Nie ma jeszcze ułożonego grafiku, więc nie da się pokazać skutku na prawdziwych danych. Zasady zadziałają przy
        najbliższym układaniu.
      </p>
    )
  }
  return (
    <div className="grid gap-3">
      <p className="m-0 text-ink-muted">Sprawdziłem ostatni grafik ({result.period}) z nowymi zasadami, bez układania go od nowa. To nie jest
        prognoza: przy następnym układaniu grafik może się zmienić bardziej, niż tu widać.</p>
      {result.lines.length === 0 ? (
        <p className="m-0">Ta zmiana nie zmienia oceny ostatniego grafiku.</p>
      ) : (
        <ul className="m-0 grid gap-2 pl-5">
          {result.lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {result.manager_rules_before !== null && result.manager_rules_after !== null && (
        <p className="m-0 rounded-sm border border-line bg-surface px-3 py-2">
          Zgodność z zasadami kierownika: <b>{Math.round(result.manager_rules_before)} %</b> →{' '}
          <b>{Math.round(result.manager_rules_after)} %</b>
        </p>
      )}
    </div>
  )
}

const SOURCE: Record<string, { text: string; tone: 'muted' | 'accent' | 'warn' } | null> = {
  group: { text: 'z grupy', tone: 'muted' },
  location: { text: 'zmienione w tym lokalu', tone: 'accent' },
  own: { text: 'tylko w tym lokalu', tone: 'accent' },
  off: null,
}

function RuleCard({
  item,
  place,
  index,
  last,
  scope,
  data,
  disabled,
  onChange,
  onMove,
}: {
  item: Item
  place: number | null
  index: number
  last: boolean
  scope: Scope
  data: RulesOut
  disabled: boolean
  onChange: (patch: Partial<Item>) => void
  onMove: (from: number, to: number) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.code })
  const lockedHere = scope === 'group' && item.location_only
  const source = scope === 'location' ? SOURCE[item.source] : null
  const differsFromGroup =
    scope === 'location' &&
    item.group_value &&
    (item.group_value.enabled !== item.enabled ||
      item.group_value.is_hard !== item.is_hard ||
      JSON.stringify(item.group_value.params) !== JSON.stringify(item.params))

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        'grid grid-cols-[auto_1fr] gap-3 rounded-md border bg-surface p-3',
        item.enabled ? 'border-line' : 'border-dashed border-line bg-paper',
        isDragging && 'relative z-30 border-accent shadow-sheet',
      )}
    >
      <div className="grid content-start justify-items-center gap-1">
        <span
          className={cn('grid size-10 place-items-center rounded-sm text-lg font-extrabold tabular-nums', place ? 'bg-ink text-accent-ink' : 'bg-grid text-ink-muted')}
          aria-label={place ? `Miejsce ${place}` : 'Wyłączona'}
        >
          {place ?? '–'}
        </span>
        <button
          type="button"
          className="grid min-h-(--touch) min-w-(--touch) cursor-grab touch-none place-items-center rounded-sm text-ink-muted hover:bg-accent-soft active:cursor-grabbing"
          aria-label={`Przeciągnij: ${item.label}`}
          disabled={disabled}
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden="true" size={22} />
        </button>
      </div>
      <div className="grid gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="grid gap-0.5">
            <span className="flex flex-wrap items-center gap-2">
              <b className="text-lg">{item.label}</b>
              {source && <Tag tone={source.tone}>{source.text}</Tag>}
              {item.good_practice && <Tag>dobra praktyka</Tag>}
            </span>
            <span className="text-sm text-ink-muted">{item.description}</span>
          </div>
          <span className="flex gap-1">
            <Button variant="quiet" size="normal" className="px-2" aria-label={`Wyżej: ${item.label}`} disabled={disabled || index === 0} onClick={() => onMove(index, index - 1)}>
              <ArrowUp aria-hidden="true" size={20} />
            </Button>
            <Button variant="quiet" size="normal" className="px-2" aria-label={`Niżej: ${item.label}`} disabled={disabled || last} onClick={() => onMove(index, index + 1)}>
              <ArrowDown aria-hidden="true" size={20} />
            </Button>
          </span>
        </div>

        {lockedHere ? (
          <p className="m-0 text-sm text-ink-muted">Tę zasadę ustawia się w każdym lokalu osobno, bo dotyczy jego stanowisk i zmian.</p>
        ) : (
          <div className="flex flex-wrap items-start gap-x-6 gap-y-1">
            <CheckField
              label="Włączona"
              checked={item.enabled}
              disabled={disabled}
              onChange={(e) => onChange({ enabled: e.target.checked, is_hard: e.target.checked ? item.is_hard : false })}
            />
            <CheckField
              label="Bez wyjątków"
              hint={item.code === 'target_hours' ? 'Dopuszcza do 10 % odchylenia od celu.' : undefined}
              checked={item.is_hard}
              disabled={disabled || !item.enabled}
              onChange={(e) => onChange({ is_hard: e.target.checked })}
            />
            {item.param_names.filter((name) => scope === 'location' || !LOCATION_PARAMS.has(name)).map((name) => (
              <ParamInput key={name} name={name} item={item} data={data} disabled={disabled || !item.enabled} onChange={onChange} />
            ))}
          </div>
        )}
        {differsFromGroup && item.group_value && (
          <div>
            <Button
              variant="quiet"
              size="normal"
              disabled={disabled}
              onClick={() => onChange({ enabled: item.group_value!.enabled, is_hard: item.group_value!.is_hard, params: item.group_value!.params })}
            >
              Przywróć jak w grupie
            </Button>
          </div>
        )}
      </div>
    </li>
  )
}

function ParamInput({
  name,
  item,
  data,
  disabled,
  onChange,
}: {
  name: string
  item: Item
  data: RulesOut
  disabled: boolean
  onChange: (patch: Partial<Item>) => void
}) {
  const value = item.params[name]
  const set = (next: unknown) => onChange({ params: { ...item.params, [name]: next } })
  const id = `${item.code}-${name}`
  if (name === 'position' || name === 'shift_type') {
    const options = name === 'position' ? data.positions : data.shift_types
    return (
      <label htmlFor={id} className="grid gap-1 text-sm font-semibold">
        {PARAM_LABEL[name]}
        <select id={id} className={cn(inputClass, 'min-w-44')} value={(value as string) ?? ''} disabled={disabled} onChange={(e) => set(e.target.value || null)}>
          <option value="">{item.code === 'experience_mix' ? 'Wszystkie stanowiska' : 'Wybierz…'}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </label>
    )
  }
  return (
    <label htmlFor={id} className="grid gap-1 text-sm font-semibold">
      {PARAM_LABEL[name] ?? name}
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={1}
        className={cn(inputClass, 'w-24 tabular-nums')}
        value={typeof value === 'number' ? value : ''}
        disabled={disabled}
        onChange={(e) => set(e.target.value === '' ? null : Number(e.target.value))}
      />
    </label>
  )
}
