import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { SignOutButton } from './SignOutButton'

describe('SignOutButton', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says the session goes on when logging out failed, and logs out on the next try', async () => {
    let answer: [number, unknown] = [503, { detail: 'Bad Gateway' }]
    const calls = mockApi((method, path) => (method === 'POST' && path === '/api/auth/logout' ? answer : [404, {}]))
    renderScreen(<SignOutButton />)

    fireEvent.click(await screen.findByRole('button', { name: 'Wyloguj' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nie udało się wylogować. Sesja trwa dalej.')
    expect(screen.getByRole('button', { name: 'Wyloguj' })).toBeInTheDocument() // still on the same screen

    answer = [204, null]
    fireEvent.click(screen.getByRole('button', { name: 'Wyloguj jeszcze raz' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Wyloguj' })).not.toBeInTheDocument())
    expect(calls.filter((c) => c.url === '/api/auth/logout')).toHaveLength(2)
  })
})
