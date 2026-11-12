import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { LoginScreen } from './LoginScreen'

describe('LoginScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks for 9 digits before sending anything', async () => {
    const calls = mockApi(() => [200, {}])
    renderScreen(<LoginScreen />)
    fireEvent.change(await screen.findByLabelText('Numer telefonu'), { target: { value: '12 34' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij kod SMS' }))
    expect(await screen.findByText(/Wpisz 9 cyfr numeru/)).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('shows the server message for an unknown number', async () => {
    mockApi(() => [404, { detail: 'Nie znamy tego numeru. Poproś kierownika o zaproszenie.' }])
    renderScreen(<LoginScreen />)
    fireEvent.change(await screen.findByLabelText('Numer telefonu'), { target: { value: '512 345 678' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij kod SMS' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie znamy tego numeru')
  })

  it('goes to the code step and checks the code after the sixth digit', async () => {
    const calls = mockApi((_method, path) =>
      path === '/api/auth/request-code'
        ? [200, { phone: '+48512345678', expires_in_s: 300, resend_after_s: 60 }]
        : [400, { detail: 'To nie jest dobry kod. Zostały 4 próby.' }],
    )
    renderScreen(<LoginScreen />)
    fireEvent.change(await screen.findByLabelText('Numer telefonu'), { target: { value: '512345678' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij kod SMS' }))
    expect(await screen.findByText('+48 512 345 678')).toBeInTheDocument()
    expect(calls[0].body).toEqual({ phone: '+48512345678', purpose: 'login' })
    fireEvent.change(screen.getByLabelText('Kod z SMS-a, 6 cyfr'), { target: { value: '12345' } })
    expect(calls).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('Kod z SMS-a, 6 cyfr'), { target: { value: '123456' } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Zostały 4 próby')
    expect(calls[1].body).toEqual({ phone: '+48512345678', code: '123456' })
    expect(screen.getByRole('button', { name: /Wyślij kod jeszcze raz za/ })).toBeDisabled()
  })
})
