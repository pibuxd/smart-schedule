import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { ScheduleScreen } from './ScheduleScreen'
import { AsManager } from './test-utils'

const period = {
  id: 'p1',
  location_id: 'l1',
  start: '2026-12-01',
  end: '2026-12-02',
  status: 'draft',
  deadline: '2026-11-24',
  availability_requested_at: null,
  published_version_id: null,
  latest_version_id: 'v1',
  latest_version_status: 'draft',
  active_run_id: null,
  manual_changes: 0,
  experienced_short: [],
  missing_availability: 0,
}

const scores = {
  holes: 1,
  slots: 3,
  manager_rules: 91.25,
  employee_requests: 88,
  stability_changes: 0,
  hard_violations: 0,
  unmeasured_rules: 1,
  unscored_requests: 2,
  is_complete: false,
  is_valid: true,
  notes: [],
}

function shift(id: string, date: string, employee: [string, string] | null, extra = {}) {
  return {
    id,
    date,
    start_time: '06:00',
    end_time: '14:00',
    hours: 8,
    shift_type_name: 'Ranna',
    position_id: 'pos1',
    position_name: 'Sprzedawca',
    employee_id: employee?.[0] ?? null,
    employee_name: employee?.[1] ?? '',
    pinned: false,
    manual: false,
    borrowed: false,
    wish: employee ? 'neutral' : null,
    problems: [],
    past: false,
    ...extra,
  }
}

const version = {
  id: 'v1',
  number: 1,
  status: 'draft',
  created_at: '2026-11-25T10:00:00+01:00',
  published_at: null,
  editable: true,
  period,
  location_id: 'l1',
  location_name: 'Wieliczka – Rynek',
  scores,
  shifts: [
    shift('s1', '2026-12-01', ['e1', 'Anna Wróbel'], { pinned: true }),
    shift('s2', '2026-12-01', ['e2', 'Marek Zając'], { wish: 'neutral', manual: true }),
    shift('s3', '2026-12-02', null),
  ],
  employees: [
    { id: 'e1', name: 'Anna Wróbel', position_ids: ['pos1'], hours: 8, shifts: 1, target_hours: 100, max_hours: 120, active: true },
    { id: 'e2', name: 'Marek Zając', position_ids: ['pos1'], hours: 8, shifts: 1, target_hours: null, max_hours: null, active: true },
  ],
  positions: [{ id: 'pos1', name: 'Sprzedawca' }],
  hard_problems: [],
  rules: [
    { code: 'max_consecutive_days', label: 'Dni pracy z rzędu', hard: false, percent: 100, broken: 0, examples: [] },
    { code: 'fair_closings', label: 'Równy podział zamknięć', hard: false, percent: null, broken: 0, examples: [] },
  ],
  unmet_requests: [
    { employee_name: 'Marek Zając', text: 'Prosi o wolne 1 grudnia.', kind: 'text', percent_kept: 0 },
    { employee_name: 'Anna Wróbel', text: 'Nie chcę zamykać w piątki.', kind: 'unscored', percent_kept: null },
  ],
  notes: ['Grafik ułożony w 12 s.'],
  changed_people: [] as string[],
  history: [
    { id: 'v1', number: 1, status: 'draft', created_at: '2026-11-25T10:00:00+01:00', published_at: null, generated: true, created_by_name: 'Teresa Gawlik' },
  ],
}

const explanation = {
  shift: shift('s3', '2026-12-02', null),
  summary: 'Tę zmianę może wziąć 1 osoba z listy niżej.',
  candidates: [
    {
      employee_id: 'e1',
      name: 'Anna Wróbel',
      current: false,
      possible: true,
      problems: [],
      clash: false,
      notes: [],
      wish: 'prefer',
      hours: 16,
      target_hours: 100,
      max_hours: 120,
      holes: 0,
      manager_rules: 92,
      employee_requests: 90,
    },
    {
      employee_id: 'e2',
      name: 'Marek Zając',
      current: false,
      possible: false,
      problems: ['Marek Zając ma zaznaczone „nie mogę” (02.12 Ranna 06:00–14:00).'],
      clash: false,
      notes: [],
      wish: 'cannot',
      hours: 16,
      target_hours: null,
      max_hours: null,
      holes: 0,
      manager_rules: 91,
      employee_requests: 80,
    },
  ],
  history: [
    { at: '2026-11-20T10:00:00+01:00', reason: 'offer', from_name: 'Ola Kos', to_name: '', by_name: 'Piotr' },
  ],
}

const fine = { ok: true, problems: [], warnings: [], before: scores, after: scores, clashes: [], problems_if_removed: [], ok_if_removed: true }

// Marek works at Rynek at the same time; the explanation offers to move him here.
const busyElsewhere = {
  ...explanation,
  candidates: [
    {
      ...explanation.candidates[1],
      problems: ['Marek Zając ma dwie zmiany w tym samym czasie: wt. 02.12 Ranna i Rynek 06:00–14:00.'],
      clash: true,
      wish: 'neutral',
    },
  ],
}

function clashCheck(clash: Record<string, unknown> = {}) {
  const item = {
    shift_id: 'r1',
    employee_id: 'e2',
    kind: 'published',
    location_name: 'Rynek',
    text: 'Marek Zając ma w tym czasie zmianę w grafiku lokalu Rynek: wt. 02.12, 06:00–14:00.',
    can_remove: true,
    reason: '',
    ...clash,
  }
  return { ...fine, ok: false, problems: ['Marek Zając ma dwie zmiany w tym samym czasie.'], clashes: [item], ok_if_removed: item.can_remove }
}

function api(overrides: Record<string, unknown> = {}) {
  return mockApi((method, path) => {
    if (method === 'GET' && path === '/api/locations/l1/periods') return [200, [overrides.period ?? period]]
    if (method === 'GET' && path === '/api/versions/v1') return [200, overrides.version ?? version]
    if (method === 'GET' && path.endsWith('/explain')) return [200, overrides.explanation ?? explanation]
    if (method === 'POST' && path.endsWith('/check')) return [200, overrides.check ?? fine]
    if (method === 'PATCH') return [200, fine]
    if (method === 'POST' && path.endsWith('/publish')) return [200, version.history[0]]
    if (method === 'POST' && path.endsWith('/pin')) return [200, { ok: true }]
    return [404, { detail: 'Nie ma.' }]
  })
}

function show() {
  renderScreen(
    <AsManager>
      <ScheduleScreen locationId="l1" today={new Date(2026, 10, 26)} />
    </AsManager>,
  )
}

describe('ScheduleScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the three scores, an incomplete schedule, the grid and what is left to the manager', async () => {
    api()
    show()
    expect(await screen.findByText('Wersja 1')).toBeInTheDocument()
    expect(screen.getByText('Nie wszystkie zmiany są obsadzone.')).toBeInTheDocument()
    expect(screen.getByText('91,3 %')).toBeInTheDocument()
    expect(screen.getByText('Do Twojej oceny: 2.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Anna Wróbel, 06:00–14:00, przypięta/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Marek Zając.*zmieniona ręcznie/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Bez obsady/ })).toBeInTheDocument()
    expect(screen.getByText('nic do oceny')).toBeInTheDocument()
    expect(screen.getByText('Nie chcę zamykać w piątki.')).toBeInTheDocument()
  })

  it('shows what a replacement would change when the manager opens an assigned shift', async () => {
    const shift = version.shifts.find((item) => item.employee_id)!
    const reason = 'Po zamianie na osobę Ewa grafik gorzej spełnia polecenie kierownika „Praca 1 grudnia”.'
    mockApi((method, path) => {
      if (method === 'GET' && path.endsWith('/periods')) return [200, [period]]
      if (method === 'GET' && path === '/api/versions/v1') return [200, version]
      if (method === 'GET' && path.endsWith('/explain')) return [200, { ...explanation, shift, reasons: [reason] }]
      return [404, { detail: 'Nie ma.' }]
    })
    show()
    fireEvent.click((await screen.findAllByRole('button', { name: new RegExp(shift.employee_name) }))[0])
    expect(await screen.findByRole('heading', { name: 'Co uzasadnia ten przydział w obecnym grafiku?' })).toBeInTheDocument()
    expect(await screen.findByText(reason)).toBeInTheDocument()
  })

  it('explains an empty shift and puts a person in it', async () => {
    const calls = api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Bez obsady/ }))
    const sheet = await screen.findByRole('dialog')
    expect(await within(sheet).findByText('Tę zmianę może wziąć 1 osoba z listy niżej.')).toBeInTheDocument()
    expect(within(sheet).getByText(/Marek Zając ma zaznaczone „nie mogę”/)).toBeInTheDocument()
    expect(within(sheet).getByText('Historia tej zmiany (1)')).toBeInTheDocument()
    expect(within(sheet).getByText(/oddana zmiana/)).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Wpisz: Anna Wróbel' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!).toMatchObject({
      url: '/api/versions/v1/assignments',
      body: { changes: [{ shift_id: 's3', employee_id: 'e1' }], remove_clashes: false },
    })
  })

  it('asks before taking a person off their shift in another location', async () => {
    const calls = api({ explanation: busyElsewhere, check: clashCheck() })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Bez obsady/ }))
    const sheet = await screen.findByRole('dialog')
    expect(await within(sheet).findByText(/przenieść tutaj kogoś, kto ma w tym czasie inną zmianę/)).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Przenieś tutaj: Marek Zając' }))
    const question = await within(sheet).findByRole('alertdialog', { name: 'Ta osoba ma w tym czasie inną zmianę' })
    expect(within(question).getByText(/w grafiku lokalu Rynek: wt. 02.12/)).toBeInTheDocument()
    expect(within(question).getByText(/Damy znać tej osobie i kierownikowi tamtego lokalu/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
    fireEvent.click(within(question).getByRole('button', { name: 'Tak, przenieś tutaj' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({
      changes: [{ shift_id: 's3', employee_id: 'e2' }],
      remove_clashes: true,
    })
  })

  it('says why a person cannot be taken off a shift in a location the manager does not run', async () => {
    const reason = 'Nie prowadzisz lokalu Rynek, więc poproś jego kierownika o zmianę.'
    const calls = api({ explanation: busyElsewhere, check: clashCheck({ can_remove: false, reason }) })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Bez obsady/ }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Przenieś tutaj: Marek Zając' }))
    const question = await within(sheet).findByRole('alertdialog')
    expect(within(question).getByText(reason)).toBeInTheDocument()
    expect(within(question).queryByRole('button', { name: 'Tak, przenieś tutaj' })).not.toBeInTheDocument()
    fireEvent.click(within(question).getByRole('button', { name: 'Zamknij' }))
    expect(within(sheet).queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('keeps an empty shift empty on purpose and shows what to do when nobody can take it', async () => {
    const calls = mockApi((method, path) => {
      if (method === 'GET' && path === '/api/locations/l1/periods') return [200, [period]]
      if (method === 'GET' && path === '/api/versions/v1') return [200, version]
      if (method === 'GET' && path.endsWith('/explain')) {
        return [200, { ...explanation, candidates: explanation.candidates.filter((c) => !c.possible) }]
      }
      if (method === 'POST' && path.endsWith('/pin')) return [200, { ok: true }]
      return [404, { detail: 'Nie ma.' }]
    })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Bez obsady/ }))
    const sheet = await screen.findByRole('dialog')
    expect(await within(sheet).findByText('Nikt nie może wziąć tej zmiany.')).toBeInTheDocument()
    expect(within(sheet).getByRole('link', { name: 'zmniejszyć obsadę tego dnia' })).toHaveAttribute(
      'href',
      '/kierownik/lokal/l1/ustawienia',
    )
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zostaw pustą na stałe' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/pin'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/pin'))!.body).toEqual({ pinned: true })
  })

  it('publishes after a warning about unfilled shifts', async () => {
    const calls = api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Opublikuj' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/W grafiku są dziury: 1 zmiana bez obsady/)).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Opublikuj mimo braków' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/versions/v1/publish')).toBe(true))
  })

  it('pins all unpinned manual changes in one go', async () => {
    const calls = api()
    show()
    expect(await screen.findByText(/Ręczne poprawki bez przypięcia: 1\. Znikną, jeśli ułożysz grafik od nowa/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Przypnij poprawki (1)' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/versions/v1/shifts/s2/pin')).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/pin'))).toMatchObject({ body: { pinned: true } })
  })

  it('names the people a correction changes before publishing', async () => {
    api({ version: { ...version, changed_people: ['Anna Wróbel', 'Marek Zając'] } })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Opublikuj' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Zmieniasz zmiany tych osób: Anna Wróbel, Marek Zając/)).toBeInTheDocument()
  })

  it('a published schedule can be looked at but corrected only through a new draft', async () => {
    api({
      version: { ...version, status: 'published', editable: false, history: [{ ...version.history[0], status: 'published' }] },
    })
    show()
    expect(await screen.findByRole('button', { name: 'Popraw grafik' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Opublikuj' })).not.toBeInTheDocument()
    expect(screen.getByText(/Ten grafik widzą pracownicy w „Mój grafik”/)).toBeInTheDocument()
  })

  it('says what to do before anything is arranged', async () => {
    api({ period: { ...period, status: 'collecting', latest_version_id: null, latest_version_status: null } })
    show()
    expect(await screen.findByText('Grafik nie jest jeszcze ułożony')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ułóż grafik' })).toBeInTheDocument()
  })

  it('has an error state', async () => {
    mockApi(() => [500, { detail: 'Błąd serwera.' }])
    show()
    expect(await screen.findByText('Błąd serwera.')).toBeInTheDocument()
  })
})
