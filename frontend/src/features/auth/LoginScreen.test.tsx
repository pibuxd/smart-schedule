import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { LoginScreen } from './LoginScreen'

describe('LoginScreen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.sessionStorage.clear()
  })

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
    expect(screen.getByRole('timer')).toHaveTextContent('Nowy kod możesz dostać za 1:00')
    expect(screen.queryByRole('button', { name: /Wyślij kod jeszcze raz/ })).not.toBeInTheDocument()
    // The typed code stays, and the old message goes away as soon as a digit changes.
    expect(screen.getByLabelText('Kod z SMS-a, 6 cyfr')).toHaveValue('123456')
    fireEvent.change(screen.getByLabelText('Kod z SMS-a, 6 cyfr'), { target: { value: '12345' } })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('sends a number from another country with its code', async () => {
    const calls = mockApi(() => [200, { phone: '+380501234567', expires_in_s: 300, resend_after_s: 60 }])
    renderScreen(<LoginScreen />)
    expect(await screen.findByLabelText('Kraj numeru')).toHaveValue('PL')
    fireEvent.change(screen.getByLabelText('Kraj numeru'), { target: { value: 'UA' } })
    expect(screen.getByText('+380')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Numer telefonu'), { target: { value: '050 123 45 67' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij kod SMS' }))
    expect(await screen.findByText('+380 501 234 567')).toBeInTheDocument()
    // The server drops the national 0 and answers with the stored form.
    expect(calls[0].body).toEqual({ phone: '+3800501234567', purpose: 'login' })
  })

  it('takes a number typed with + whatever country is picked', async () => {
    const calls = mockApi(() => [200, { phone: '+995555123456', expires_in_s: 300, resend_after_s: 60 }])
    renderScreen(<LoginScreen />)
    fireEvent.change(await screen.findByLabelText('Numer telefonu'), { target: { value: '+995 555 12 34 56' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij kod SMS' }))
    expect(await screen.findByText('Wpisz kod z SMS-a')).toBeInTheDocument()
    expect(calls[0].body).toEqual({ phone: '+995555123456', purpose: 'login' })
  })

  it('keeps the code step after a page refresh', async () => {
    mockApi(() => [200, { phone: '+48512345678', expires_in_s: 300, resend_after_s: 60 }])
    const first = renderScreen(<LoginScreen />)
    fireEvent.change(await screen.findByLabelText('Numer telefonu'), { target: { value: '512345678' } })
    fireEvent.click(screen.getByRole('button', { name: 'Wyślij kod SMS' }))
    expect(await screen.findByText('Wpisz kod z SMS-a')).toBeInTheDocument()
    first.unmount()
    renderScreen(<LoginScreen />)
    expect(await screen.findByText('Wpisz kod z SMS-a')).toBeInTheDocument()
    expect(screen.getByText('+48 512 345 678')).toBeInTheDocument()
  })
})
