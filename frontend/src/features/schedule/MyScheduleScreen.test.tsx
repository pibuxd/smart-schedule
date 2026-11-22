import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { MyScheduleScreen } from './MyScheduleScreen'

const shift = {
  id: 'a1',
  date: '2026-11-13',
  start_at: '2026-11-13T06:00:00+01:00',
  end_at: '2026-11-13T14:00:00+01:00',
  start_time: '06:00',
  end_time: '14:00',
  hours: 8,
  location_name: 'Wieliczka – Rynek',
  position_name: 'Sprzedawca',
  shift_type_name: 'Ranna',
  away: false,
  coworkers: ['Anna Wróbel', 'Marek Zając'],
}

const offer = {
  id: 'o1',
  shift: {
    date: '2026-11-20',
    start_time: '14:00',
    end_time: '22:00',
    hours: 8,
    location_id: 'l2',
    location_name: 'Bochnia',
    position_name: 'Sprzedawca',
    shift_type_name: 'Popołudniowa',
  },
  offered_by_name: 'Ola Kos',
  away: true,
  my_claim_id: null,
  my_claim_status: null,
}

function schedule(shifts: unknown[], offers: unknown[] = []) {
  return mockApi((method, path) => {
    if (path === '/api/me/offers') return [200, offers]
    if (method === 'POST' && path === '/api/me/shifts/a1/offer') return [201, { id: 'o9', status: 'open', notified: 3, notified_here: 1 }]
    if (method === 'POST' && path === '/api/offers/o1/claim') return [201, { ...offer, my_claim_id: 'c1', my_claim_status: 'pending' }]
    return [200, { home_location_name: 'Wieliczka – Rynek', shifts, months: [{ month: '2026-11', hours: 112 }] }]
  })
}

describe('MyScheduleScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the next shift as a big calendar page and the month total', async () => {
    schedule([shift])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    const next = await screen.findByRole('article', { name: 'Najbliższa zmiana' })
    expect(next).toHaveTextContent('jutro')
    expect(next).toHaveTextContent('13')
    expect(next).toHaveTextContent('6:00–14:00')
    expect(next).toHaveTextContent('Z Tobą: Anna Wróbel, Marek Zając')
    expect(screen.getByText('Razem w listopadzie')).toBeInTheDocument()
    expect(screen.getByText('112 godz.')).toBeInTheDocument()
    expect(screen.queryByText(/Wypłata to godziny razy stawka/)).not.toBeInTheDocument()
  })

  it('shows the pay under the hours only when the manager set rates', async () => {
    mockApi((_method, path) => {
      if (path === '/api/me/offers') return [200, []]
      return [
        200,
        {
          home_location_name: 'Wieliczka – Rynek',
          shifts: [shift],
          months: [
            { month: '2026-11', hours: 112, pay: 3516.8, supplements_pay: 36, unpriced_hours: 0 },
            { month: '2026-12', hours: 40, pay: 251.2, supplements_pay: 0, unpriced_hours: 32 },
            { month: '2027-01', hours: 16, pay: null, unpriced_hours: 16 },
          ],
        },
      ]
    })
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    await screen.findByText('Razem w listopadzie')
    const pay = screen.getAllByText('Wypłata brutto')
    expect(pay).toHaveLength(2) // January has no rates at all: no pay line
    expect(pay[0].parentElement).toHaveTextContent(/3516,80\szł/)
    expect(pay[1].parentElement).toHaveTextContent(/251,20\szł/)
    expect(screen.getByText('Bez 32 godz., bo kierownik nie ustawił dla nich stawki.')).toBeInTheDocument()
    expect(screen.getAllByText(/W tym dodatki/)).toHaveLength(1) // November only: December has none
    expect(screen.getByText(/W tym dodatki: 36,00\szł\./)).toBeInTheDocument()
    expect(screen.queryByText(/szacun/i)).not.toBeInTheDocument()
  })

  it('keeps an ongoing shift visible without offering it and skips an ended shift', async () => {
    schedule([shift])
    const first = renderScreen(<MyScheduleScreen companyId="c1" today={new Date(shift.start_at)} />)
    expect(await screen.findByText('Trwa Twoja zmiana')).toBeInTheDocument()
    expect(screen.queryByText('Oddaj tę zmianę')).not.toBeInTheDocument()
    first.unmount()
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(shift.end_at)} />)
    expect(await screen.findByText('Nie masz jeszcze zmian w grafiku')).toBeInTheDocument()
    expect(screen.getByText('112 godz.')).toBeInTheDocument()
  })

  it('gives a shift away after explaining that it stays mine until the manager decides', async () => {
    const calls = schedule([shift])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Oddaj tę zmianę' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText('Dopóki kierownik nie zdecyduje, to nadal Twoja zmiana.')).toBeInTheDocument()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Oddaj zmianę' }))
    expect(await within(sheet).findByText(/Daliśmy znać 3 osobom: 1 z Twojego lokalu i 2 z innych lokali firmy/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/me/shifts/a1/offer')).toBe(true)
  })

  it('shows a shift being given away and lets me keep it', async () => {
    schedule([{ ...shift, offer_id: 'o9', offer_status: 'claimed' }])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Oddajesz: czeka na kierownika' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Ktoś chce wziąć tę zmianę/)).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: 'Jednak nie oddaję' })).toBeInTheDocument()
  })

  it('lists shifts to take and asks for one', async () => {
    const calls = schedule([shift], [offer])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    const section = await screen.findByRole('region', { name: 'Zmiany do wzięcia' })
    expect(section).toHaveTextContent('Bochnia (inny lokal). Oddaje: Ola Kos')
    fireEvent.click(within(section).getByRole('button', { name: 'Weź zmianę' }))
    expect(calls.some((c) => c.url === '/api/offers/o1/claim')).toBe(false) // one more tap first
    fireEvent.click(within(section).getByRole('button', { name: 'Tak, zgłoś mnie' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/offers/o1/claim')).toBe(true))
  })

  it('takes a shift at once when the location hands shifts over without approval', async () => {
    let taken = false
    const calls = mockApi((method, path) => {
      if (path === '/api/me/offers') return [200, taken ? [] : [{ ...offer, at_once: true }]]
      if (method === 'POST' && path === '/api/offers/o1/claim') {
        taken = true
        return [201, { ...offer, my_claim_id: 'c1', my_claim_status: 'approved', at_once: true }]
      }
      return [200, { home_location_name: 'Wieliczka – Rynek', shifts: [shift], months: [{ month: '2026-11', hours: 112 }] }]
    })
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    const section = await screen.findByRole('region', { name: 'Zmiany do wzięcia' })
    fireEvent.click(within(section).getByRole('button', { name: 'Weź zmianę' }))
    expect(within(section).getByText(/Od razu będzie Twoja/)).toBeInTheDocument()
    fireEvent.click(within(section).getByRole('button', { name: 'Tak, biorę' }))
    expect(await screen.findByText('Zmiana jest Twoja.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/offers/o1/claim')).toBe(true)
  })

  it('says the first taker gets my shift when the location needs no approval', async () => {
    schedule([{ ...shift, handover_at_once: true }])
    renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Oddaj tę zmianę' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText(/Pierwsza osoba, która ją weźmie, dostaje ją od razu/)).toBeInTheDocument()
    expect(within(sheet).getByText('Dopóki nikt jej nie weźmie, to nadal Twoja zmiana.')).toBeInTheDocument()
  })

  it('hides giving away in read-only mode', async () => {
    schedule([shift])
    renderScreen(<MyScheduleScreen companyId="c1" readOnly today={new Date(2026, 10, 12)} />)
    await screen.findByRole('article', { name: 'Najbliższa zmiana' })
    expect(screen.queryByRole('button', { name: 'Oddaj tę zmianę' })).not.toBeInTheDocument()
  })

  it('explains an empty schedule and points to "Kiedy mogę"', async () => {
    schedule([])
    renderScreen(<MyScheduleScreen companyId="c1" />)
    expect(await screen.findByText('Nie masz jeszcze zmian w grafiku')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'kiedy możesz pracować' })).toBeInTheDocument()
  })

  it('shows a plain error with a retry button', async () => {
    mockApi(() => [500, {}])
    renderScreen(<MyScheduleScreen companyId="c1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać grafiku')
    expect(screen.getByRole('button', { name: 'Spróbuj jeszcze raz' })).toBeInTheDocument()
  })

  describe('other hours', () => {
    function withHours(shifts: unknown[], recent: unknown[] = []) {
      return mockApi((method, path) => {
        if (path === '/api/me/offers') return [200, []]
        if (method === 'POST' && path === '/api/me/hours-changes') return [201, { id: 'h9', status: 'pending' }]
        if (method === 'POST' && path === '/api/hours-changes/h1/cancel') return [200, { id: 'h1', status: 'cancelled' }]
        return [200, { home_location_name: 'Wieliczka – Rynek', shifts, recent, months: [{ month: '2026-11', hours: 112 }] }]
      })
    }

    it('reports leaving a running shift early with "Wychodzę teraz"', async () => {
      const calls = withHours([{ ...shift, can_report: true }])
      const now = new Date(Date.parse(shift.start_at) + 5 * 3_600_000)
      renderScreen(<MyScheduleScreen companyId="c1" today={now} />)
      fireEvent.click(await screen.findByRole('button', { name: 'Zgłoś inne godziny' }))
      const sheet = await screen.findByRole('dialog')
      expect(within(sheet).getByRole('status')).toHaveTextContent('To te same godziny, które liczą się teraz.')
      expect(within(sheet).getByRole('button', { name: 'Wyślij kierownikowi' })).toBeDisabled()

      // The screen was opened at 11:00; the click comes at 11:15 by the location's clock.
      vi.useFakeTimers({ toFake: ['Date'] })
      vi.setSystemTime(new Date(Date.parse(shift.start_at) + 5.25 * 3_600_000))
      fireEvent.click(within(sheet).getByRole('button', { name: 'Wychodzę teraz' }))
      vi.useRealTimers()
      fireEvent.change(within(sheet).getByLabelText('Powód (nie musisz pisać)'), { target: { value: 'źle się czuję' } })
      expect(within(sheet).getByRole('status')).toHaveTextContent('Krócej o 2 h 45 min')
      fireEvent.click(within(sheet).getByRole('button', { name: 'Wyślij kierownikowi' }))

      expect(await within(sheet).findByText(/Wysłane\. Kierownik zatwierdzi albo odrzuci te godziny/)).toBeInTheDocument()
      const sent = calls.find((c) => c.method === 'POST' && c.url === '/api/me/hours-changes')
      expect(sent?.body).toEqual({ assignment_id: 'a1', start_time: '06:00', end_time: '11:15', reason: 'źle się czuję' })
    })

    it('says what overtime means while typing the hours', async () => {
      withHours([{ ...shift, can_report: true }])
      renderScreen(<MyScheduleScreen companyId="c1" today={new Date(Date.parse(shift.start_at) - 3_600_000)} />)
      fireEvent.click(await screen.findByRole('button', { name: 'Zgłoś inne godziny' }))
      const sheet = await screen.findByRole('dialog')
      expect(within(sheet).queryByRole('button', { name: 'Wychodzę teraz' })).not.toBeInTheDocument() // not started yet
      fireEvent.change(within(sheet).getByLabelText('Do'), { target: { value: '15:30' } })
      expect(within(sheet).getByRole('status')).toHaveTextContent('Nadgodziny: +1 h 30 min')
    })

    it('shows approved hours, a waiting report and lets me take the report back', async () => {
      const calls = withHours([
        {
          ...shift,
          can_report: true,
          worked: { start_at: shift.start_at, end_at: '2026-11-13T15:00:00+01:00', start_time: '06:00', end_time: '15:00', hours: 9, difference_minutes: 60, by_manager: false },
          report: { id: 'h1', start_time: '06:00', end_time: '16:00', hours: 10, difference_minutes: 120, reason: '' },
        },
      ])
      renderScreen(<MyScheduleScreen companyId="c1" today={new Date(shift.start_at)} />)
      const next = await screen.findByRole('article', { name: 'Najbliższa zmiana' })
      expect(next).toHaveTextContent('6:00–15:00')
      expect(next).toHaveTextContent('W grafiku 6:00–14:00, nadgodziny: +1 h (zatwierdzone)')
      expect(next).toHaveTextContent('Zgłoszone 6:00–16:00: czeka na kierownika')

      fireEvent.click(within(next).getByRole('button', { name: 'Zgłoszone inne godziny: zmień albo wycofaj' }))
      const sheet = await screen.findByRole('dialog')
      expect(within(sheet).getByText(/Czeka na kierownika: 6:00–16:00 \(nadgodziny: \+2 h\)/)).toBeInTheDocument()
      fireEvent.click(within(sheet).getByRole('button', { name: 'Wycofaj zgłoszenie' }))
      await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/hours-changes/h1/cancel')).toBe(true))
    })

    it('offers other hours for past shifts and not for a shift next week', async () => {
      const later = { ...shift, id: 'a2', date: '2026-11-20', start_at: '2026-11-20T06:00:00+01:00', end_at: '2026-11-20T14:00:00+01:00', can_report: true }
      const past = { ...shift, id: 'a0', date: '2026-11-10', start_at: '2026-11-10T06:00:00+01:00', end_at: '2026-11-10T14:00:00+01:00', can_report: true }
      withHours([later], [past])
      renderScreen(<MyScheduleScreen companyId="c1" today={new Date(2026, 10, 12)} />)
      await screen.findByRole('article', { name: 'Najbliższa zmiana' })
      expect(screen.queryByRole('button', { name: 'Zgłoś inne godziny' })).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('Minione zmiany'))
      fireEvent.click(await screen.findByRole('button', { name: 'Inne godziny' }))
      expect(await screen.findByRole('dialog')).toHaveTextContent('w grafiku 6:00–14:00')
    })

    it('moves a shift that just ended to the past shifts, with other hours at hand', async () => {
      withHours([{ ...shift, can_report: true }])
      renderScreen(<MyScheduleScreen companyId="c1" today={new Date(shift.end_at)} />)
      fireEvent.click(await screen.findByText('Minione zmiany'))
      fireEvent.click(await screen.findByRole('button', { name: 'Inne godziny' }))
      expect(await screen.findByRole('dialog')).toHaveTextContent('w grafiku 6:00–14:00')
    })

    it('hides reporting in read-only mode', async () => {
      withHours([{ ...shift, can_report: true }])
      renderScreen(<MyScheduleScreen companyId="c1" readOnly today={new Date(shift.start_at)} />)
      await screen.findByText('Trwa Twoja zmiana')
      expect(screen.queryByRole('button', { name: 'Zgłoś inne godziny' })).not.toBeInTheDocument()
    })
  })
})
