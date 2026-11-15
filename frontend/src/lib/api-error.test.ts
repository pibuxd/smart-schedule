import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/http'
import { errorMessage, NETWORK_PROBLEM, SERVER_PROBLEM } from './api-error'

describe('errorMessage', () => {
  const fallback = 'Nie udało się wczytać grafiku. Sprawdź internet i spróbuj jeszcze raz.'

  it('shows the message the API sent', () => {
    expect(errorMessage(new ApiError(409, { detail: 'Grafik już się układa.' }), fallback)).toBe('Grafik już się układa.')
  })

  it('does not blame the internet when the server failed', () => {
    expect(errorMessage(new ApiError(500, undefined), fallback)).toBe(`Nie udało się wczytać grafiku. ${SERVER_PROBLEM}`)
    expect(errorMessage(new ApiError(502, undefined), NETWORK_PROBLEM)).toBe(SERVER_PROBLEM)
  })

  it('keeps the network hint when there was no answer at all', () => {
    expect(errorMessage(new TypeError('Failed to fetch'), fallback)).toBe(fallback)
  })
})
