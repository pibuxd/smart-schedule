import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { EmployeeChatProvider, EmployeeChatTab } from './EmployeeChat'
import { RequestsSection } from './RequestsSection'

const period = {
  id: 'p1',
  location_name: 'Rynek',
  start: '2026-12-01',
  end: '2026-12-31',
  status: 'collecting',
  deadline: '2099-11-24',
  editable: true,
}

function api(asked: typeof period | null) {
  return mockApi((_method, path) =>
    path === '/api/me/availability'
      ? [200, { period: asked, days: [], submitted_at: null, assistant_reads: true }]
      : [200, []],
  )
}

const show = (screenUi = <p>Mój grafik</p>, readOnly = false) =>
  renderScreen(
    <EmployeeChatProvider companyId="c1" readOnly={readOnly}>
      {screenUi}
      <EmployeeChatTab />
    </EmployeeChatProvider>,
  )

const asked = (calls: { url: string }[]) => calls.filter((c) => c.url.startsWith('/api/me/requests?')).map((c) => c.url)

describe('Assistant button on every employee screen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opens the conversation of the period the manager asked for', async () => {
    const calls = api(period)
    show()
    // The tab of the phone's bar; on a computer the corner button (both in the page, CSS shows one).
    fireEvent.click((await screen.findAllByRole('button', { name: 'Asystent' })).at(-1)!)
    expect(await screen.findByRole('dialog', { name: 'Asystent' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Twoja wiadomość')).toBeInTheDocument()
    expect(asked(calls)).toContain('/api/me/requests?company_id=c1&period_id=p1')
    // Written on another screen, a request still says which month it is for.
    expect(screen.getByText('Prośby na grudzień 2026.')).toBeInTheDocument()
  })

  it('talks about this month before the manager asks', async () => {
    const calls = api(null)
    show()
    fireEvent.click((await screen.findAllByRole('button', { name: 'Asystent' }))[0])
    const today = new Date()
    const month = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`
    await waitFor(() => expect(asked(calls)).toContain(`/api/me/requests?company_id=c1&month=${month}`))
  })

  it('on "Kiedy mogę" talks about the month on screen', async () => {
    const calls = api(period)
    show(<RequestsSection companyId="c1" month="2027-01-01" editable assistantReads />)
    expect(await screen.findByText('Twoje prośby')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Asystent' }).at(-1)!)
    expect(await screen.findByRole('dialog', { name: 'Asystent' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/W czym pomóc/)).toBeInTheDocument())
    expect(asked(calls).every((url) => url.endsWith('month=2027-01-01'))).toBe(true)
    expect(screen.getByText('Prośby na styczeń 2027.')).toBeInTheDocument()
  })

  it('has no button while the company has no access', async () => {
    api(period)
    show(<p>Mój grafik</p>, true)
    expect(await screen.findByText('Mój grafik')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Asystent' })).not.toBeInTheDocument()
  })
})
