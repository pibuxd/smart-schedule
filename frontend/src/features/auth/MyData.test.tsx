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

it('saves any bank account number for pay in "Twoje dane" and shows an error in words', async () => {
  let answer: [number, unknown] = [400, { detail: 'Numer konta może mieć najwyżej 100 znaków.' }]
  const calls = mockApi((method) => (method === 'PATCH' ? answer : [404, { detail: 'Nie ma.' }]))
  renderScreen(<MyDataButton me={me} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Twoje dane' }))
  const sheet = await screen.findByRole('dialog', { name: 'Twoje dane' })
  expect(within(sheet).getByText('Logujesz się numerem +48 600 100 001.')).toBeInTheDocument()
  expect(within(sheet).getByText('Nieobowiązkowy. Widzą go tylko Twoi kierownicy (też w pliku z godzinami) i administrator Grafikomatu.')).toBeInTheDocument()
  const field = within(sheet).getByLabelText('Numer konta do wypłaty')
  expect(field).not.toHaveAttribute('inputmode') // a Revolut or Ukrainian number has letters
  fireEvent.change(field, { target: { value: 'Revolut LT12 3250 0123 4567 8910' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz dane' }))
  expect(await within(sheet).findByText('Numer konta może mieć najwyżej 100 znaków.')).toBeInTheDocument()

  answer = [200, { ...me, bank_account: 'Revolut LT12 3250 0123 4567 8910' }]
  fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz dane' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)[1]).toEqual({
    first_name: 'Ola',
    last_name: 'Nowak',
    bank_account: 'Revolut LT12 3250 0123 4567 8910',
  })
})

it('leaves a saved number alone when only the name changes', async () => {
  const saved = { ...me, bank_account: 'PL61 1090 1014 0000 0712 1981 2874' }
  const calls = mockApi((method) => (method === 'PATCH' ? [200, saved] : [404, { detail: 'Nie ma.' }]))
  renderScreen(<MyDataButton me={saved} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Twoje dane' }))
  const sheet = await screen.findByRole('dialog', { name: 'Twoje dane' })
  const field = within(sheet).getByLabelText('Numer konta do wypłaty')
  expect(field).toHaveValue('PL61 1090 1014 0000 0712 1981 2874')
  // Extra spaces are not a change.
  fireEvent.change(field, { target: { value: ' PL61 1090 1014  0000 0712 1981 2874 ' } })
  fireEvent.change(within(sheet).getByLabelText('Imię'), { target: { value: 'Aleksandra' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Zapisz dane' }))
  await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ first_name: 'Aleksandra', last_name: 'Nowak' }))
})
