import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/http'
import { errorMessage, NETWORK_PROBLEM, SERVER_PROBLEM, shouldRetry } from './api-error'

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

describe('shouldRetry', () => {
  it('waits out a restart of the API during a deploy', () => {
    expect(shouldRetry(0, new ApiError(503, undefined))).toBe(true)
    expect(shouldRetry(3, new ApiError(502, undefined))).toBe(true)
    expect(shouldRetry(4, new ApiError(503, undefined))).toBe(false)
    expect(shouldRetry(2, new TypeError('Failed to fetch'))).toBe(true)
  })

  it('asks once more after another server error and never after an answer', () => {
    expect(shouldRetry(0, new ApiError(500, undefined))).toBe(true)
    expect(shouldRetry(1, new ApiError(500, undefined))).toBe(false)
    expect(shouldRetry(0, new ApiError(404, { detail: 'Nie znaleziono.' }))).toBe(false)
    expect(shouldRetry(0, new ApiError(409, { detail: 'Zajęte.' }))).toBe(false)
  })
})
