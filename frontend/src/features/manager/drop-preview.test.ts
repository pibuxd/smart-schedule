import { describe, expect, it } from 'vitest'

import type { CheckOut, VersionShiftOut } from '../../api/generated/model'
import { dropWords, isDropTarget } from './drop-preview'

const shift = (id: string, employee: [string, string] | null) =>
  ({ id, employee_id: employee?.[0] ?? null, employee_name: employee?.[1] ?? '' }) as VersionShiftOut

const anna = shift('s1', ['e1', 'Anna Wróbel'])
const marek = shift('s2', ['e2', 'Marek Zając'])
const hole = shift('s3', null)
const scores = { manager_rules: 91.25, employee_requests: 88 }
const check = (extra: Partial<CheckOut>) =>
  ({ ok: true, problems: [], warnings: [], before: scores, after: scores, ...extra }) as CheckOut

describe('dropWords', () => {
  it('asks for another shift when there is nothing to drop on', () => {
    expect(dropWords(anna, undefined, undefined).what).toBe('Upuść na innej zmianie, żeby zamienić osoby.')
    expect(isDropTarget(anna, anna)).toBe(false)
    expect(isDropTarget(anna, shift('s9', ['e1', 'Anna Wróbel']))).toBe(false)
  })

  it('says at once what the drop does, with no "checking" text while the answer is on its way', () => {
    expect(dropWords(anna, marek, undefined)).toEqual({ what: 'Zamiana z: Marek Zając', verdict: null, bad: false })
    expect(dropWords(anna, hole, undefined).what).toBe('Przeniesienie na zmianę bez obsady')
  })

  it('shows the scores after a swap that is allowed', () => {
    expect(dropWords(anna, marek, check({}))).toMatchObject({ verdict: 'Można. Zasady 91,3 %, prośby 88 %.', bad: false })
  })

  it('shows the first problem of a swap that breaks a rule, and a failed check', () => {
    const refused = check({ ok: false, problems: ['Anna Wróbel ma dwie zmiany tego dnia.'] })
    expect(dropWords(anna, marek, refused)).toMatchObject({ verdict: 'Anna Wróbel ma dwie zmiany tego dnia.', bad: true })
    expect(dropWords(anna, marek, 'failed')).toMatchObject({ verdict: 'Nie udało się sprawdzić tej zamiany.', bad: true })
  })
})
