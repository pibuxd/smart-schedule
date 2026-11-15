import { describe, expect, it } from 'vitest'

import type { VersionOut } from '../../api/generated/model'
import { verdict } from './verdict'

const base = {
  scores: { holes: 0, hard_violations: 0, unscored_requests: 0 },
  rules: [],
  unmet_requests: [],
} as unknown as VersionOut

const make = (patch: Record<string, unknown>) => ({ ...base, ...patch, scores: { ...base.scores, ...(patch.scores ?? {}) } }) as VersionOut

describe('verdict', () => {
  it('praises a schedule with nothing to check', () => {
    expect(verdict(base)).toBe('Dobry grafik. Wszystkie zmiany obsadzone, zasady i prośby spełnione.')
  })

  it('puts holes and hard problems first', () => {
    expect(verdict(make({ scores: { holes: 2 } }))).toContain('2 zmiany bez obsady')
    expect(verdict(make({ scores: { holes: 2, hard_violations: 1 } }))).toContain('łamie zasady bez wyjątków')
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
    expect(verdict(data)).toBe('Dobry grafik. Wszystkie zmiany obsadzone. Do sprawdzenia: 3 rzeczy, opisane niżej.')
  })
})
