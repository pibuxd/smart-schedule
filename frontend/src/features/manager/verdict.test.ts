import { describe, expect, it } from 'vitest'

import type { VersionOut } from '../../api/generated/model'
import { verdict } from './verdict'

const base = {
  scores: { holes: 0, hard_violations: 0, unscored_requests: 0 },
  rules: [],
  unmet_requests: [],
  hard_problems: [],
} as unknown as VersionOut

const make = (patch: Record<string, unknown>) => ({ ...base, ...patch, scores: { ...base.scores, ...(patch.scores ?? {}) } }) as VersionOut

describe('verdict', () => {
  it('praises a schedule with nothing to check', () => {
    expect(verdict(base)).toBe('Wszystkie zmiany obsadzone, zasady i prośby spełnione.')
  })

  it('puts holes and hard problems first', () => {
    expect(verdict(make({ scores: { holes: 2 } }))).toContain('2 zmiany bez obsady')
    expect(verdict(make({ scores: { holes: 2 }, hard_problems: ['Ewa ma dwie zmiany.'] }))).toContain('łamie zasady bez wyjątków')
    // Kept by the manager on purpose (fewer experienced people): not a reason to hold the schedule back.
    expect(verdict(make({ scores: { hard_violations: 1 }, accepted_problems: ['Ma być doświadczona osoba.'] })))
      .toBe('Wszystkie zmiany obsadzone, zasady i prośby spełnione.')
  })

  it('counts what is left to look at', () => {
    const data = make({
      rules: [
        { hard: false, broken: 1 },
        { hard: false, broken: 0 },
      ],
      unmet_requests: [{ kind: 'text' }, { kind: 'unscored' }],
      scores: { unscored_requests: 1 },
    })
    expect(verdict(data)).toBe('Wszystkie zmiany obsadzone. Do sprawdzenia: 3 rzeczy, opisane niżej.')
  })

  it('does not call a partly kept rule "spełniona"', () => {
    const data = make({ rules: [{ hard: false, broken: 0, percent: 95 }, { hard: false, broken: 0, percent: null }] })
    expect(verdict(data)).toBe('Wszystkie zmiany obsadzone. Do sprawdzenia: 1 rzecz, opisane niżej.')
  })

  it('counts every unmet request, not only the listed ones', () => {
    const data = make({ unmet_requests: [{ kind: 'text' }, { kind: 'instruction' }], unmet_request_count: 31 })
    expect(verdict(data)).toBe('Wszystkie zmiany obsadzone. Do sprawdzenia: 32 rzeczy, opisane niżej.')
  })
})
