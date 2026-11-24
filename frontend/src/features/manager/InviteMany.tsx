import { useQueryClient } from '@tanstack/react-query'
import { FileUp, MessageCircle, Pencil, Users, X } from 'lucide-react'
import { useId, useRef, useState } from 'react'

import type {
  InvitedPeopleOut,
  ListedPersonOut,
  ManagerOverviewOut,
  PeopleListOut,
  PositionOut,
} from '../../api/generated/model'
import { useInviteMany, useManagerOverview, useReadPeopleList } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { CheckField, Tag, TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { prettyPhone } from '../auth/phone'
import { useAssistantDrawer } from './assistant-drawer'
import { useManager } from './ManagerContext'
import { people, persons } from './words'

// Same limit as the server (`people_list.MAX_FILE_BYTES`): a bigger file is refused before sending.
const MAX_FILE_BYTES = 2 * 1024 * 1024
const FILE_TYPES = '.csv,.txt,.tsv,.xlsx,.pdf,text/csv,text/plain,application/pdf'

type Row = ListedPersonOut & { key: number; editing: boolean }

/** "Zaproś kilka osób": the button and the sheet with a pasted list or a file, a preview to correct, one send. */
export function InviteManyButton({ locationId, positions }: { locationId: string; positions: PositionOut[] }) {
  const { readOnly } = useManager()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="secondary" size="normal" disabled={readOnly} onClick={() => setOpen(true)}>
        <Users aria-hidden="true" size={20} />
        Zaproś kilka osób
      </Button>
      <Sheet
        open={open}
        onOpenChange={setOpen}
        title="Zaproś kilka osób"
        description="Wklej listę albo wybierz plik. Przed wysłaniem sprawdzisz każdą osobę."
      >
        {open && <InviteMany locationId={locationId} positions={positions} onClose={() => setOpen(false)} />}
      </Sheet>
    </>
  )
}

function InviteMany({
  locationId,
  positions,
  onClose,
}: {
  locationId: string
  positions: PositionOut[]
  onClose: () => void
}) {
  const { companyId } = useManager()
  const queryClient = useQueryClient()
  const drawer = useAssistantDrawer()
  const read = useReadPeopleList()
  const inviteMany = useInviteMany()
  const overview = useManagerOverview({ company_id: companyId }, { query: { staleTime: 60_000 } })
  const locations = new Map(
    ((overview.data?.data as ManagerOverviewOut | undefined)?.locations ?? []).map((l) => [l.id, l.name]),
  )
  const names = new Map(positions.map((p) => [p.id, p.name]))
  const fileInput = useRef<HTMLInputElement>(null)
  const pasteId = useId()
  const [text, setText] = useState('')
  const [rows, setRows] = useState<Row[] | null>(null)
  const [skippedLines, setSkippedLines] = useState(0)
  const [fileProblem, setFileProblem] = useState<string | null>(null)
  const [invited, setInvited] = useState(0)
  const nextKey = useRef(0)

  const toRows = (people: ListedPersonOut[]): Row[] =>
    people.map((person) => ({ ...person, key: nextKey.current++, editing: false }))
  const onRead = (response: { status: number; data: unknown }) => {
    if (response.status !== 200) return
    const list = response.data as PeopleListOut
    setRows(toRows(list.people))
    setSkippedLines(list.skipped_lines)
  }
  const readFile = (file: File | undefined) => {
    setFileProblem(null)
    if (!file) return
    if (file.size > MAX_FILE_BYTES) {
      setFileProblem('Plik jest za duży. Najwyżej 2 MB: podziel listę na mniejsze części.')
      return
    }
    read.mutate({ locationId, data: { file } }, { onSuccess: onRead })
  }
  const change = (key: number, fields: Partial<Row>) =>
    // A corrected person is checked again on sending.
    setRows((now) => (now ?? []).map((row) => (row.key === key ? { ...row, ...fields, problem: null } : row)))
  const ready = (rows ?? []).filter((row) => !row.problem)
  const fix = (rows ?? []).length - ready.length

  const send = () => {
    if (!rows || ready.length === 0) return
    inviteMany.mutate(
      {
        locationId,
        data: {
          people: ready.map((row) => ({
            phone: row.phone,
            first_name: row.first_name,
            last_name: row.last_name,
            position_ids: row.position_ids,
            location_id: row.location_id,
          })),
        },
      },
      {
        onSuccess: (response) => {
          if (response.status !== 200) return
          const result = response.data as InvitedPeopleOut
          setInvited((count) => count + result.invited.length)
          // Who was invited leaves the list; who was not comes back with the reason, next to those still to fix.
          setRows([...rows.filter((row) => row.problem), ...toRows(result.skipped)])
          void queryClient.invalidateQueries()
        },
      },
    )
  }

  if (rows === null) {
    return (
      <div className="grid gap-4">
        <div className="grid gap-1">
          <label htmlFor={pasteId} className="text-sm font-semibold">
            Wklej listę
          </label>
          <textarea
            id={pasteId}
            rows={6}
            value={text}
            maxLength={40_000}
            onChange={(event) => setText(event.target.value)}
            placeholder={'Anna Kowalska 512 345 678 Kasa\nJan Nowak 600 100 200'}
            className="min-h-32 w-full rounded-sm border-2 border-line bg-surface px-3 py-2 text-base text-ink focus:border-accent"
          />
          <p className="m-0 text-sm text-ink-muted">Jedna osoba w wierszu: imię, nazwisko i numer. Może być stanowisko.</p>
        </div>
        <Button wide disabled={!text.trim() || read.isPending} onClick={() => read.mutate({ locationId, data: { text } }, { onSuccess: onRead })}>
          {read.isPending ? 'Sprawdzam…' : 'Sprawdź listę'}
        </Button>
        <div className="flex items-center gap-3 text-sm text-ink-muted" aria-hidden="true">
          <span className="h-px flex-1 bg-line" />
          albo
          <span className="h-px flex-1 bg-line" />
        </div>
        <input
          ref={fileInput}
          type="file"
          accept={FILE_TYPES}
          className="sr-only"
          aria-label="Plik z listą osób"
          onChange={(event) => {
            readFile(event.target.files?.[0])
            event.target.value = ''
          }}
        />
        <Button variant="secondary" wide disabled={read.isPending} onClick={() => fileInput.current?.click()}>
          <FileUp aria-hidden="true" size={20} />
          Wybierz plik (CSV, Excel, PDF)
        </Button>
        {(fileProblem || read.isError) && (
          <InlineError>{fileProblem ?? errorMessage(read.error, NETWORK_PROBLEM)}</InlineError>
        )}
        {drawer && (
          <p className="m-0 flex flex-wrap items-center gap-x-2 text-sm text-ink-muted">
            Plik w innym układzie? Przeczyta go asystent.
            <Button
              variant="quiet"
              size="normal"
              className="text-sm"
              onClick={() => {
                onClose()
                drawer.openChat({ locationId })
              }}
            >
              <MessageCircle aria-hidden="true" size={16} />
              Otwórz asystenta
            </Button>
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      {invited > 0 && (
        <p role="status" className="m-0 rounded-sm bg-accent-soft px-3 py-2 text-accent">
          {`Zaproszono ${persons(invited)}. Nie wysyłamy SMS-ów, więc powiedz im, żeby zalogowały się w Grafikomacie swoim numerem.`}
        </p>
      )}
      {rows.length > 0 && (
        <p className="m-0">
          {fix > 0
            ? `Na liście: ${people(rows.length)}. Do poprawienia: ${fix}.`
            : `Na liście: ${people(rows.length)}. Sprawdź imiona i numery.`}
          {skippedLines > 0 && invited === 0 && (
            <span className="block text-sm text-ink-muted">{`Pominięte wiersze bez numeru telefonu: ${skippedLines}.`}</span>
          )}
        </p>
      )}
      <ul className="m-0 grid list-none gap-2 p-0">
        {rows.map((row) => (
          <PersonRow
            key={row.key}
            row={row}
            here={row.location_id === locationId}
            locationName={locations.get(row.location_id) ?? 'inny lokal'}
            positions={positions}
            names={names}
            onChange={(fields) => change(row.key, fields)}
            onRemove={() => setRows(rows.filter((other) => other.key !== row.key))}
          />
        ))}
      </ul>
      {inviteMany.isError && <InlineError>{errorMessage(inviteMany.error, NETWORK_PROBLEM)}</InlineError>}
      {ready.length > 0 ? (
        <Button wide disabled={inviteMany.isPending} onClick={send}>
          {inviteMany.isPending ? 'Zapraszam…' : `Zaproś ${persons(ready.length)}`}
        </Button>
      ) : (
        rows.length === 0 && (
          <Button wide onClick={onClose}>
            Gotowe
          </Button>
        )
      )}
      <Button
        variant="quiet"
        size="normal"
        onClick={() => {
          setRows(null)
          setInvited(0)
          read.reset()
        }}
      >
        Wczytaj inną listę
      </Button>
    </div>
  )
}

function PersonRow({
  row,
  here,
  locationName,
  positions,
  names,
  onChange,
  onRemove,
}: {
  row: Row
  here: boolean
  locationName: string
  positions: PositionOut[]
  names: Map<string, string>
  onChange: (fields: Partial<Row>) => void
  onRemove: () => void
}) {
  const name = `${row.first_name} ${row.last_name}`.trim() || 'Bez imienia'
  const toggle = (id: string) =>
    onChange({
      position_ids: row.position_ids.includes(id) ? row.position_ids.filter((x) => x !== id) : [...row.position_ids, id],
    })
  return (
    <li className={`grid gap-2 rounded-md border bg-surface px-3 py-2 ${row.problem ? 'border-cannot' : 'border-line'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="grid min-w-0">
          <b className="truncate">{name}</b>
          <span className="text-sm text-ink-muted tabular-nums">
            {/^\+48\d{9}$/.test(row.phone) ? prettyPhone(row.phone) : row.phone || 'brak numeru'}
          </span>
        </span>
        <span className="flex shrink-0 gap-1">
          <Button
            variant="quiet"
            size="normal"
            aria-expanded={row.editing}
            aria-label={`Popraw: ${name}`}
            onClick={() => onChange({ editing: !row.editing })}
          >
            <Pencil aria-hidden="true" size={16} />
            Popraw
          </Button>
          <Button variant="quiet" size="normal" aria-label={`Usuń z listy: ${name}`} onClick={onRemove}>
            <X aria-hidden="true" size={18} />
          </Button>
        </span>
      </div>
      {(row.position_ids.length > 0 || !here || row.unknown_positions.length > 0) && (
        <span className="flex flex-wrap gap-1">
          {here && row.position_ids.map((id) => <Tag key={id}>{names.get(id) ?? 'Stanowisko'}</Tag>)}
          {!here && <Tag tone="accent">{`Lokal: ${locationName}`}</Tag>}
          {row.unknown_positions.map((position) => (
            <Tag key={position} tone="warn">{`Nie ma stanowiska: ${position}`}</Tag>
          ))}
        </span>
      )}
      {row.problem && (
        <p role="alert" className="m-0 text-sm font-semibold text-cannot">
          {row.problem}
        </p>
      )}
      {row.editing && (
        <div className="grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
          <TextField label="Imię" value={row.first_name} maxLength={80} onChange={(e) => onChange({ first_name: e.target.value })} />
          <TextField label="Nazwisko" value={row.last_name} maxLength={120} onChange={(e) => onChange({ last_name: e.target.value })} />
          <TextField
            label="Numer telefonu"
            type="tel"
            inputMode="tel"
            autoComplete="off"
            className="sm:col-span-2"
            value={row.phone}
            maxLength={40}
            onChange={(e) => onChange({ phone: e.target.value })}
          />
          {here && positions.length > 0 && (
            <fieldset className="m-0 grid gap-0 border-0 p-0 sm:col-span-2">
              <legend className="mb-1 text-sm font-semibold">Stanowiska</legend>
              {positions.map((p) => (
                <CheckField key={p.id} label={p.name} checked={row.position_ids.includes(p.id)} onChange={() => toggle(p.id)} />
              ))}
            </fieldset>
          )}
        </div>
      )}
    </li>
  )
}
