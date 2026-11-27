import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderScreen } from '../../test/render'
import { PhonePushSwitch } from './PhonePushSwitch'

const native = vi.hoisted(() => ({ app: true }))
const push = vi.hoisted(() => ({ pushSwitch: vi.fn(), setPush: vi.fn() }))
vi.mock('../../native/platform', async (original) => ({
  ...(await original<typeof import('../../native/platform')>()),
  isNativeApp: () => native.app,
}))
vi.mock('../../native/push', () => push)

const me = { id: 'p1', first_name: 'Ola', last_name: 'Kos', phone: '+48500100200', companies: [] }

describe('PhonePushSwitch', () => {
  beforeEach(() => {
    native.app = true
    vi.clearAllMocks()
    mockApi(() => [200, me])
  })
  afterEach(() => vi.unstubAllGlobals())

  it('turns push off for this phone', async () => {
    push.pushSwitch.mockResolvedValue({ available: true, on: true, blocked: false })
    push.setPush.mockResolvedValue({ available: true, on: false, blocked: false })
    renderScreen(<PhonePushSwitch />)

    const toggle = await screen.findByRole('switch', { name: 'Na tym telefonie' })
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(toggle)

    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'))
    expect(push.setPush).toHaveBeenCalledWith('p1', false)
  })

  it('says so when the server could not be told, and stays on', async () => {
    push.pushSwitch.mockResolvedValue({ available: true, on: true, blocked: false })
    push.setPush.mockRejectedValue(new Error('offline'))
    renderScreen(<PhonePushSwitch />)

    fireEvent.click(await screen.findByRole('switch'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wyłączyć.')
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  })

  it('points to the phone settings when the phone blocks the notifications', async () => {
    push.pushSwitch.mockResolvedValue({ available: true, on: false, blocked: true })
    renderScreen(<PhonePushSwitch />)

    expect(await screen.findByRole('switch')).toBeDisabled()
    expect(screen.getByText('Zezwól na powiadomienia w ustawieniach telefonu.')).toBeInTheDocument()
  })

  it('is not there in a build without push', async () => {
    push.pushSwitch.mockResolvedValue({ available: false })
    renderScreen(<PhonePushSwitch />)
    await waitFor(() => expect(push.pushSwitch).toHaveBeenCalledWith('p1'))
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('is not there on the web', async () => {
    native.app = false
    const calls = mockApi(() => [200, me])
    renderScreen(<PhonePushSwitch />)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(push.pushSwitch).not.toHaveBeenCalled()
    expect(screen.queryByRole('switch')).toBeNull()
  })
})
