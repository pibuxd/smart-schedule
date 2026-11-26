import { describe, expect, it } from 'vitest'

import { pushTarget } from './push'

describe('pushTarget', () => {
  it('opens the route and company a notification is about', () => {
    expect(pushTarget({ path: '/grafik?dzien=2026-12-04', company_id: 'c1' })).toEqual({
      path: '/grafik?dzien=2026-12-04',
      companyId: 'c1',
    })
    expect(pushTarget({ path: '/kierownik/oddane-zmiany?oferta=6a1e%2F1' })).toEqual({
      path: '/kierownik/oddane-zmiany?oferta=6a1e%2F1',
      companyId: undefined,
    })
  })

  it('never leaves the app', () => {
    for (const path of ['//evil.example/x', 'https://evil.example', 'javascript:alert(1)', '/grafik?x=<b>', '']) {
      expect(pushTarget({ path })).toBeNull()
    }
    expect(pushTarget(null)).toBeNull()
    expect(pushTarget({ path: 7 })).toBeNull()
  })
})
