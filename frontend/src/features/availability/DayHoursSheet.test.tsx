import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DayHoursSheet } from './DayHoursSheet'

describe('DayHoursSheet', () => {
  it('shows saved hours between the half hours as they are', () => {
    // Tests of PR #82 (26.11.2026): "nie mogę 9:15–11:45" saved windows the lists could not show, so they read 0:00.
    render(
      <DayHoursSheet
        date="2026-12-07"
        mark={{ state: 'neutral', from: '00:00', to: '09:15', from2: '11:45', to2: '00:00' }}
        onClose={() => {}}
        onSave={() => {}}
      />,
    )
    const [, firstEnd, secondStart] = screen.getAllByRole('combobox') as HTMLSelectElement[]
    expect(firstEnd.value).toBe('09:15')
    expect(secondStart.value).toBe('11:45')
    expect(screen.getAllByRole('option', { name: '9:15' }).length).toBeGreaterThan(0)
  })
})
