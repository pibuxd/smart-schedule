import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MyCalendarOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { AvailabilityScreen } from './AvailabilityScreen'
import { EmployeeChatProvider } from './EmployeeChat'

const period = {
  id: 'p1',
  location_name: 'Wieliczka – Rynek',
  start: '2026-12-01',
  end: '2026-12-31',
  status: 'collecting' as const,
  deadline: '2099-11-24',
  editable: true,
}

const TODAY = new Date(2026, 10, 13)

type Server = {
  period?: typeof period | null
  submitted_at?: string | null
  locked?: string[]
  days?: MyCalendarOut['days']
  location_names?: string[]
}

/** The two reads of the screen (the open request, then one month of the calendar) and every write. */
function api({ period: asked = period, submitted_at = null, locked = [], days, location_names = ['Rynek'] }: Server = {}) {
  const marked = days ?? [{ date: '2026-12-04', state: 'prefer' as const, from_time: '22:00:00', to_time: '06:00:00' }]
  return mockApi((method, path) => {
    if (path === '/api/me/requests') return [200, []]
    if (path === '/api/me/calendar' && method === 'GET') {
      // The test server answers for December whatever month is asked; enough for one screen.
      return [200, { start: '2026-12-01', end: '2026-12-31', days: marked, locked, period: asked, submitted_at, location_names }]
    }
    if (path === '/api/me/calendar') return [204, null]
    return [200, { period: asked, days: [], submitted_at }]
  })
}

// As in the employee layout: the chat with "Twoje prośby" lives around the screen.
const show = (readOnly = false) =>
  renderScreen(
    <EmployeeChatProvider companyId="c1" readOnly={readOnly}>
      <AvailabilityScreen companyId="c1" readOnly={readOnly} today={TODAY} />
    </EmployeeChatProvider>,
  )

describe('AvailabilityScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is open for marking ahead when the manager has not asked yet', async () => {
    const calls = api({ period: null, days: [] })
    show()
    expect(await screen.findByText(/Zaznacz, kiedy możesz pracować w kolejnych miesiącach/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Listopad 2026' })).toBeInTheDocument()
    expect(await screen.findByText('Wybierz, a potem zaznacz dni:')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Wyślij kierownikowi/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Następny miesiąc' }))
    expect(screen.getByRole('heading', { name: 'Grudzień 2026' })).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.url.includes('/api/me/calendar?'))).toHaveLength(2))
    expect(calls.some((c) => c.url.includes('start=2026-12-01&end=2026-12-31'))).toBe(true)
  })

  it('takes a request for the month before the manager asks', async () => {
    const calls = api({ period: null, days: [] })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Napisz prośbę' }))
    const box = await screen.findByLabelText('Twoja prośba')
    expect(screen.getByText(/Prośba dotyczy tego miesiąca/)).toBeInTheDocument()
    fireEvent.change(box, { target: { value: 'W grudniu bez nocek.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij prośbę' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/me/requests')).toBe(true))
    expect(calls.find((c) => c.method === 'POST' && c.url === '/api/me/requests')?.body).toEqual({
      company_id: 'c1',
      month: '2026-12-01',
      text: 'W grudniu bez nocek.',
    })
  })

  it('opens on the period the manager asked about and shows the deadline', async () => {
    api()
    show()
    expect(await screen.findByRole('heading', { name: 'Grudzień 2026' })).toBeInTheDocument()
    expect(await screen.findByText(/Zaznacz, kiedy możesz pracować w grudniu/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Wyślij kierownikowi' })).toBeInTheDocument()
  })

  it('does not let days with an arranged schedule be changed', async () => {
    const calls = api({ locked: ['2026-12-01', '2026-12-02'] })
    show()
    await screen.findByText('Wybierz, a potem zaznacz dni:')
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: mogę, nie da się zmienić' }), { detail: 0 })
    expect(screen.getByRole('button', { name: 'wtorek 1 grudnia: mogę, nie da się zmienić' })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })

  it('says that availability is shared when the person works in several locations', async () => {
    api({ location_names: ['Rynek', 'Dworcowa'] })
    show()
    expect(await screen.findByText(/Pracujesz w kilku lokalach \(Rynek, Dworcowa\)\. Dyspozycje są wspólne/)).toBeInTheDocument()
  })

  it('shows states with words for screen readers, including night hours', async () => {
    api()
    show()
    const day = await screen.findByRole('button', { name: 'piątek 4 grudnia: chętnie, tylko 22:00–06:00 (do rana)' })
    expect(day).toHaveTextContent('22–6')
    expect(screen.getByRole('button', { name: 'wtorek 1 grudnia: mogę' })).toBeInTheDocument()
  })

  it('marks a day with the chosen state and saves it', async () => {
    const calls = api()
    show()
    await screen.findByText('Wybierz, a potem zaznacz dni:')
    fireEvent.click(screen.getByRole('button', { name: 'Nie mogę' }))
    // A keyboard press (detail 0) paints one day, like a tap does.
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: mogę' }), { detail: 0 })
    expect(screen.getByRole('button', { name: 'wtorek 1 grudnia: nie mogę' })).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(1))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      company_id: 'c1',
      days: [{ date: '2026-12-01', state: 'cannot', from_time: null, to_time: null }],
    })

    expect(screen.queryByRole('button', { name: 'Cofnij' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Więcej opcji' })).not.toBeInTheDocument()
  })

  it('finishes a delayed write before sending the next choice for the same day', async () => {
    const calls = api()
    const respond = globalThis.fetch
    let release!: () => void
    const delayed = new Promise<void>((resolve) => { release = resolve })
    let writes = 0
    vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
      if (init.method === 'PUT' && ++writes === 1) await delayed
      return respond(url, init)
    })
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'wtorek 1 grudnia: mogę' }), { detail: 0 })
    await waitFor(() => expect(writes).toBe(1))
    fireEvent.click(screen.getByRole('button', { name: 'Chętnie' }))
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: nie mogę' }), { detail: 0 })
    release()
    await screen.findByText('Zapisane')
    const saved = calls.filter((c) => c.method === 'PUT').map((c) => (c.body as { days: { state: string }[] }).days[0].state)
    expect(saved).toEqual(['cannot', 'prefer'])
  })

  it('warns plainly that "chętnie" with hours blocks other shifts that day', async () => {
    api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: /Godziny dnia/ }))
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: mogę' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Chętnie' }))
    fireEvent.click(screen.getByRole('radio', { name: /Mogę tylko w tych godzinach/ }))
    expect(screen.getByText('Zmiany spoza godzin 14:00–22:00 tego dnia nie dostaniesz.')).toBeInTheDocument()
  })

  it('saves two windows in a day with "albo" (only one shift)', async () => {
    const calls = api()
    show()
    fireEvent.click(await screen.findByRole('button', { name: /Godziny dnia/ }))
    fireEvent.click(screen.getByRole('button', { name: 'wtorek 1 grudnia: mogę' }))
    fireEvent.click(await screen.findByRole('radio', { name: /Mogę tylko w tych godzinach/ }))
    fireEvent.change(screen.getByLabelText('Od'), { target: { value: '06:00' } })
    fireEvent.change(screen.getByLabelText('Do'), { target: { value: '10:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Dodaj drugi przedział' }))
    fireEvent.change(screen.getAllByLabelText('Od')[1], { target: { value: '16:00' } })
    fireEvent.click(screen.getByRole('radio', { name: /Albo: tylko jedna zmiana/ }))
    expect(screen.getByText('Zmiany spoza godzin 6:00–10:00 i 16:00–22:00 tego dnia nie dostaniesz.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Zapisz ten dzień' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')!.body).toMatchObject({
      days: [
        {
          date: '2026-12-01',
          state: 'neutral',
          from_time: '06:00',
          to_time: '10:00',
          from_time_2: '16:00',
          to_time_2: '22:00',
          one_shift: true,
        },
      ],
    })
  })

  it('opens a day with its hours when it is tapped with the state it already has', async () => {
    api()
    show()
    expect(await screen.findByText('Dni z godzinami')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Chętnie' }))
    fireEvent.click(screen.getByRole('button', { name: /^piątek 4 grudnia: chętnie/ }), { detail: 0 })
    expect(await screen.findByRole('dialog', { name: 'piątek 4 grudnia' })).toBeInTheDocument()
    expect(screen.getByLabelText('Od')).toHaveValue('22:00')
    expect(screen.getByLabelText('Do')).toHaveValue('06:00')
  })

  it('cannot be changed when the company is read-only', async () => {
    api()
    show(true)
    expect(await screen.findByText(/wstrzymany dostęp/)).toBeInTheDocument()
    expect(await screen.findByRole('grid')).toBeInTheDocument()
    expect(screen.queryByText('Wybierz, a potem zaznacz dni:')).not.toBeInTheDocument()
  })
})
