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
    shift_type_id: 'st1',
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
    forced: false,
    overridden: [],
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
  accepted_problems: [],
  rules: [
    { code: 'max_consecutive_days', label: 'Dni pracy z rzędu', hard: false, percent: 100, broken: 0, examples: [] },
    { code: 'fair_closings', label: 'Równy podział zamknięć', hard: false, percent: null, broken: 0, examples: [] },
  ],
  unmet_requests: [
    { employee_name: 'Marek Zając', text: 'Prosi o wolne 1 grudnia.', kind: 'text', percent_kept: 0 },
    { employee_name: 'Anna Wróbel', text: 'Nie chcę zamykać w piątki.', kind: 'unscored', percent_kept: null },
  ],
  unmet_request_count: 1,
  notes: ['Grafik ułożony w 12 s.'],
  changed_people: [] as string[],
  today: '2026-11-26',
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
      can_force: false,
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
      can_force: true,
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
    if (method === 'GET' && path === '/api/versions/v1/employees/e2/fit') {
      return [
        200,
        [
          { shift_id: 's1', fit: 'cannot', reason: 'ma inną zmianę w tym czasie' },
          { shift_id: 's3', fit: 'prefer', reason: 'chętnie' },
        ],
      ]
    }
    if (method === 'POST' && path.endsWith('/check')) return [200, overrides.check ?? fine]
    if (method === 'PATCH') return [200, fine]
    if (method === 'POST' && path.endsWith('/publish')) return [200, version.history[0]]
    if (method === 'POST' && path.endsWith('/pin')) return [200, { ok: true }]
    if (method === 'POST' && path.endsWith('/seats')) return [201, shift('s4', '2026-12-02', null)]
    if (method === 'DELETE') return [204, null]
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

  it('folds the rules and the unmet requests, with what is inside said in the heading', async () => {
    api()
    show()
    const rules = (await screen.findByRole('heading', { name: 'Jak grafik trzyma się zasad' })).closest('details')
    expect(rules).not.toHaveAttribute('open')
    // One rule has nothing to measure, so the heading does not claim all are kept.
    expect(rules?.querySelector('summary')).toHaveTextContent('żadna nie jest złamana')
    const requests = screen.getByRole('heading', { name: 'Niespełnione prośby' }).closest('details')
    expect(requests).not.toHaveAttribute('open')
    expect(requests?.querySelector('summary')).toHaveTextContent('1 prośba · 1 do Twojej oceny')
    fireEvent.click(screen.getByRole('heading', { name: 'Niespełnione prośby' }))
    expect(requests).toHaveAttribute('open')
    expect(screen.getByText('Prosi o wolne 1 grudnia.')).toBeVisible()
  })

  it('says a rule kept in part is not fully kept, even with no counted break', async () => {
    const rules = [
      { code: 'hours_target', label: 'Cel godzin', hard: false, percent: 95, broken: 0, examples: [] },
      { code: 'fair_closings', label: 'Równy podział zamknięć', hard: false, percent: null, broken: 0, examples: [] },
    ]
    api({ version: { ...version, rules } })
    show()
    const heading = await screen.findByRole('heading', { name: 'Jak grafik trzyma się zasad' })
    expect(heading.closest('summary')).toHaveTextContent('1 spełniona częściowo')
    expect(heading.closest('summary')).not.toHaveTextContent('wszystkie spełnione')
  })

  it('shows only "do Twojej oceny" when the app could not check the requests itself', async () => {
    const unmet_requests = [{ employee_name: 'Anna Wróbel', text: 'Nie chcę zamykać w piątki.', kind: 'unscored', percent_kept: null }]
    api({ version: { ...version, unmet_requests, unmet_request_count: 0 } })
    show()
    const heading = await screen.findByRole('heading', { name: 'Niespełnione prośby' })
    expect(heading.closest('summary')?.textContent).toMatch(/1 do Twojej oceny$/)
    expect(heading.closest('summary')).not.toHaveTextContent('wszystkie spełnione')
  })

  it('counts every unmet request from the server, not only the listed ones', async () => {
    api({ version: { ...version, unmet_request_count: 31 } })
    show()
    const heading = await screen.findByRole('heading', { name: 'Niespełnione prośby' })
    expect(heading.closest('summary')).toHaveTextContent('31 próśb · 1 do Twojej oceny')
    expect(screen.getByText('I jeszcze 30 innych.')).toBeInTheDocument()
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
      force: false,
      remove_clashes: true,
    })
  })

  it('takes a person off their other shift and saves anyway with one answer', async () => {
    const left = 'Marek Zając ma zaznaczone „nie mogę” (02.12 Ranna 06:00–14:00).'
    const check = { ...clashCheck(), ok_if_removed: false, problems_if_removed: [left], can_force_if_removed: true }
    const calls = api({ explanation: busyElsewhere, check })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Bez obsady/ }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Przenieś tutaj: Marek Zając' }))
    const question = await within(sheet).findByRole('alertdialog')
    expect(within(question).getByText(left)).toBeInTheDocument()
    fireEvent.click(within(question).getByRole('button', { name: 'Tak, przenieś mimo to' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({
      changes: [{ shift_id: 's3', employee_id: 'e2' }],
      force: true,
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

  it('lets the manager put in a person who cannot work, as an override', async () => {
    const calls = api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: /^Bez obsady/ }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Wpisz mimo to: Marek Zając' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({
      changes: [{ shift_id: 's3', employee_id: 'e2' }],
      force: true,
      remove_clashes: false,
    })
  })

  it('lets the manager correct a day that has passed and marks an override', async () => {
    const past = shift('s3', '2026-12-02', ['e2', 'Marek Zając'], {
      past: true,
      forced: true,
      overridden: ['Marek Zając ma zaznaczone „nie mogę” (02.12 Ranna 06:00–14:00).'],
    })
    const calls = mockApi((method, path) => {
      if (method === 'GET' && path === '/api/locations/l1/periods') return [200, [period]]
      if (method === 'GET' && path === '/api/versions/v1') return [200, { ...version, shifts: [past] }]
      if (method === 'GET' && path.endsWith('/explain')) {
        const current = { ...explanation.candidates[1], current: true }
        return [200, { ...explanation, shift: past, candidates: [current, explanation.candidates[0]] }]
      }
      if (method === 'POST' && path.endsWith('/check')) return [200, fine]
      if (method === 'PATCH') return [200, fine]
      return [404, { detail: 'Nie ma.' }]
    })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /Marek Zając.*wpisana mimo przeszkód/ }))
    const sheet = await screen.findByRole('dialog')
    expect(await within(sheet).findByText(/Ten dzień już minął. Popraw, jeśli pracował ktoś inny/)).toBeInTheDocument()
    expect(within(sheet).getByText('Wpisane mimo przeszkód')).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Wpisz: Anna Wróbel' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
  })

  it('colours the grid for the picked person: where they want to, can and cannot work', async () => {
    api()
    show()
    fireEvent.change(await screen.findByLabelText('Pokaż, kiedy ta osoba chce i może pracować'), { target: { value: 'e2' } })
    expect(await screen.findByRole('button', { name: /^Bez obsady.*wybrana osoba chętnie/ })).toHaveClass('avail-prefer')
    expect(screen.getByRole('button', { name: /^Anna Wróbel.*wybrana osoba nie może/ })).toHaveClass('fit-cannot')
    expect(screen.getByText('nie może')).toBeInTheDocument()
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
    expect(within(sheet).getByText('usunąć to miejsce (przycisk niżej),')).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zostaw pustą na stałe' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/pin'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/pin'))!.body).toEqual({ pinned: true })
  })

  it('adds a place on a day without one and removes a place from the shift sheet', async () => {
    const calls = api({ version: { ...version, shifts: version.shifts.slice(0, 2) } })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Dodaj miejsce: Ranna · Sprzedawca, śr 2 grudnia' }))
    await waitFor(() => expect(calls.find((c) => c.url === '/api/versions/v1/seats')?.body).toEqual({
      date: '2026-12-02', shift_type_id: 'st1', position_id: 'pos1',
    }))
    expect(await screen.findByText('Dodano miejsce. Wybierz je, żeby wpisać osobę.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^Marek Zając/ }))
    const sheet = await screen.findByRole('dialog')
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Usuń miejsce (Marek Zając traci zmianę)' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/versions/v1/shifts/s2')).toBe(true))
  })

  it('does not offer new places on days that have passed', async () => {
    api({ version: { ...version, shifts: version.shifts.slice(0, 2), today: '2026-12-03' } })
    show()
    expect(await screen.findByText('Wersja 1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Dodaj miejsce/ })).not.toBeInTheDocument()
  })

  it('lets the manager publish with fewer experienced people than the staffing asks', async () => {
    const problem = 'Na zmianie 01.12 Ranna na stanowisku Sprzedawca ma być doświadczona osoba, a miejsca zajmują: Marek Zając.'
    api({ version: { ...version, scores: { ...scores, hard_violations: 1 }, accepted_problems: [problem] } })
    show()
    expect(await screen.findByText(problem)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Opublikuj' })).toBeEnabled()
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

  it('deletes the draft after asking, and the period collects availability again', async () => {
    const calls = api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Usuń szkic' }))
    const sheet = await screen.findByRole('dialog', { name: 'Usunąć szkic grafiku?' })
    expect(within(sheet).getByText(/okres wróci do zbierania dyspozycji/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(within(sheet).getByRole('button', { name: 'Tak, usuń szkic' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/versions/v1')).toBe(true))
  })

  it('says the attempt before the draft comes back', async () => {
    const h = version.history[0]
    api({
      version: {
        ...version,
        number: 3,
        history: [
          { ...h, number: 3 },
          { ...h, id: 'v2', number: 2, status: 'superseded' },
          { ...h, id: 'v1old', number: 1, status: 'superseded' },
        ],
      },
    })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Usuń szkic' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Wróci poprzedni szkic, wersja 2 z .*, z jego poprawkami i przypięciami\./)).toBeInTheDocument()
    expect(within(sheet).queryByText(/okres wróci do zbierania dyspozycji/)).not.toBeInTheDocument()
    expect(within(sheet).getByText(/Obsada dni i zmiany w grafikach innych lokali zostają/)).toBeInTheDocument()
  })

  it('deletes the older version on screen, not the current draft', async () => {
    const h = version.history[0]
    const calls = api({
      version: {
        ...version,
        id: 'v1',
        number: 1,
        status: 'superseded',
        editable: false,
        history: [{ ...h, id: 'v2', number: 2 }, { ...h, number: 1, status: 'superseded' }],
      },
    })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Usuń szkic' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Wersja 1 zniknie na dobre z historii\. Bieżący grafik zostaje bez zmian/)).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Tak, usuń szkic' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/versions/v1')).toBe(true))
  })

  it('says the published schedule stays when deleting corrections', async () => {
    const h = version.history[0]
    api({
      version: {
        ...version,
        number: 2,
        period: { ...period, status: 'published', published_version_id: 'v0' },
        history: [
          { ...h, number: 2 },
          { ...h, id: 'v0', number: 1, status: 'published', published_at: '2026-11-26T10:00:00+01:00' },
        ],
      },
    })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Usuń szkic' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Zostaje opublikowany grafik, który widzą pracownicy/)).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Zostaw' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
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
      version: {
        ...version,
        status: 'published',
        editable: false,
        published_at: '2026-11-26T10:00:00+01:00',
        history: [{ ...version.history[0], status: 'published', published_at: '2026-11-26T10:00:00+01:00' }],
      },
    })
    show()
    expect(await screen.findByRole('button', { name: 'Popraw grafik' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Opublikuj' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Usuń szkic' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Ten grafik widzą pracownicy/)).not.toBeInTheDocument()
  })

  it('shows other hours on a published shift and lets the manager change them', async () => {
    const worked = { start_at: '', end_at: '', start_time: '06:00', end_time: '15:00', hours: 9, difference_minutes: 60, by_manager: false }
    const anna = shift('s1', '2026-12-01', ['e1', 'Anna Wróbel'], { assignment_id: 'as1', worked })
    const marek = shift('s2', '2026-12-01', ['e2', 'Marek Zając'], {
      assignment_id: 'as2',
      hours_report: { id: 'h1', start_time: '06:00', end_time: '12:00', hours: 6, difference_minutes: -120, reason: '' },
    })
    const published = { ...version, status: 'published', editable: false, shifts: [anna, marek, version.shifts[2]] }
    const calls = mockApi((method, path) => {
      if (method === 'GET' && path.endsWith('/periods')) return [200, [{ ...period, status: 'published' }]]
      if (method === 'GET' && path === '/api/versions/v1') return [200, published]
      if (method === 'GET' && path.endsWith('/explain')) return [200, { ...explanation, shift: marek, candidates: [] }]
      if (method === 'POST' && path === '/api/assignments/as2/hours')
        return [200, { assignment_id: 'as2', planned_start_time: '06:00', planned_end_time: '14:00', worked: null }]
      return [404, { detail: 'Nie ma.' }]
    })
    show()
    expect(await screen.findByRole('button', { name: /Anna Wróbel, 06:00–14:00, .*naprawdę 06:00–15:00/ })).toBeInTheDocument()
    expect(screen.getByText('inne godziny (w karcie zmiany)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Marek Zając, .*czeka zgłoszenie innych godzin/ }))
    const hours = await screen.findByRole('region', { name: 'Godziny pracy' })
    expect(hours).toHaveTextContent('Liczą się godziny z grafiku: 06:00–14:00.')
    expect(hours).toHaveTextContent('Marek Zając zgłasza 06:00–12:00 (krócej o 2 h)')
    fireEvent.click(within(hours).getByRole('button', { name: 'Zmień godziny' }))
    fireEvent.change(within(hours).getByLabelText('Do'), { target: { value: '12:30' } })
    expect(within(hours).getByRole('status')).toHaveTextContent('Krócej o 1 h 30 min')
    fireEvent.click(within(hours).getByRole('button', { name: 'Zapisz godziny' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/assignments/as2/hours')?.body).toEqual({
        employee_id: 'e2',
        start_time: '06:00',
        end_time: '12:30',
        reason: '',
      }),
    )
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
