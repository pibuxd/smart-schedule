import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { MeOut } from '../../api/generated/model'
import { mockApi, renderScreen } from '../../test/render'
import { MyDataButton } from './MyData'

afterEach(() => vi.unstubAllGlobals())

const me: MeOut = {
  id: 'u1',
  phone: '+48600100001',
  first_name: 'Ola',
  last_name: 'Nowak',
  bank_account: '',
  companies: [],
  pending_invitations: 0,
}

it('saves the bank account number for pay in "Twoje dane" and shows a typo in words', async () => {
  let answer: [number, unknown] = [400, { detail: 'W tym numerze konta jest błąd. Sprawdź cyfry.' }]
  const calls = mockApi((method) => (method === 'PATCH' ? answer : [404, { detail: 'Nie ma.' }]))
  renderScreen(<MyDataButton me={me} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Twoje dane' }))
  const sheet = await screen.findByRole('dialog', { name: 'Twoje dane' })
  expect(within(sheet).getByText('Logujesz się numerem +48 600 100 001.')).toBeInTheDocument()
  expect(within(sheet).getByText('Nieobowiązkowy. Widzą go tylko Twoi kierownicy, także w pliku z godzinami do wypłaty.')).toBeInTheDocument()
  fireEvent.change(within(sheet).getByLabelText('Numer konta do wypłaty'), {
    target: { value: '61 1090 1014 0000 0712 1981 2875' },
  })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz dane' }))
  expect(await within(sheet).findByText('W tym numerze konta jest błąd. Sprawdź cyfry.')).toBeInTheDocument()

  answer = [200, { ...me, bank_account: '61109010140000071219812874' }]
  fireEvent.change(within(sheet).getByLabelText('Numer konta do wypłaty'), {
    target: { value: '61 1090 1014 0000 0712 1981 2874' },
  })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz dane' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)[1]).toEqual({
    first_name: 'Ola',
    last_name: 'Nowak',
    bank_account: '61 1090 1014 0000 0712 1981 2874',
  })
})

it('leaves a saved number alone when only the name changes', async () => {
  const saved = { ...me, bank_account: '61109010140000071219812874' }
  const calls = mockApi((method) => (method === 'PATCH' ? [200, saved] : [404, { detail: 'Nie ma.' }]))
  renderScreen(<MyDataButton me={saved} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Twoje dane' }))
  const sheet = await screen.findByRole('dialog', { name: 'Twoje dane' })
  expect(within(sheet).getByLabelText('Numer konta do wypłaty')).toHaveValue('61 1090 1014 0000 0712 1981 2874')
  fireEvent.change(within(sheet).getByLabelText('Imię'), { target: { value: 'Aleksandra' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz dane' }))
  await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ first_name: 'Aleksandra', last_name: 'Nowak' }))
})
