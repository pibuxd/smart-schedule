import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AvailabilityCalendar } from './AvailabilityCalendar'

const FIRST = 'wtorek 1 grudnia: mogę'
const SECOND = 'środa 2 grudnia: mogę'

function setup() {
  const onPaint = vi.fn()
  const onStroke = vi.fn()
  render(
    <AvailabilityCalendar
      start="2026-12-01"
      end="2026-12-07"
      marks={{}}
      disabled={false}
      onPaint={onPaint}
      onStroke={onStroke}
    />,
  )
  const first = screen.getByRole('button', { name: FIRST })
  const second = screen.getByRole('button', { name: SECOND })
  // jsdom has no layout: the finger or the mouse is "over" the second day while it moves.
  document.elementFromPoint = vi.fn(() => second)
  return { onPaint, onStroke, first, second }
}

afterEach(() => {
  Reflect.deleteProperty(document, 'elementFromPoint')
})

describe('AvailabilityCalendar', () => {
  it('lets a finger scroll: sliding over days marks nothing, a tap marks one day', () => {
    const { onPaint, onStroke, first } = setup()
    expect(first.closest('[role="grid"]')).toHaveClass('touch-manipulation')

    fireEvent.pointerDown(first, { pointerType: 'touch' })
    fireEvent.pointerMove(window, { pointerType: 'touch', clientX: 50, clientY: 50 })
    fireEvent.pointerCancel(window, { pointerType: 'touch' })
    expect(onPaint).not.toHaveBeenCalled()
    expect(onStroke).not.toHaveBeenCalled()

    fireEvent.pointerDown(first, { pointerType: 'touch' })
    fireEvent.pointerUp(first, { pointerType: 'touch' })
    fireEvent.click(first, { detail: 1 })
    expect(onPaint.mock.calls).toEqual([['2026-12-01']])
    expect(onStroke).toHaveBeenCalledTimes(1)
  })

  it('marks every day a mouse drags across, once', () => {
    const { onPaint, onStroke, first } = setup()

    fireEvent.pointerDown(first, { pointerType: 'mouse' })
    fireEvent.pointerMove(window, { pointerType: 'mouse', clientX: 50, clientY: 50 })
    fireEvent.pointerUp(window, { pointerType: 'mouse' })
    expect(onPaint.mock.calls).toEqual([['2026-12-01'], ['2026-12-02']])
    expect(onStroke).toHaveBeenCalledTimes(1)

    // A plain mouse click paints on press; the click that follows adds nothing.
    onPaint.mockClear()
    onStroke.mockClear()
    fireEvent.pointerDown(first, { pointerType: 'mouse' })
    fireEvent.pointerUp(window, { pointerType: 'mouse' })
    fireEvent.click(first, { detail: 1 })
    expect(onPaint.mock.calls).toEqual([['2026-12-01']])
    expect(onStroke).toHaveBeenCalledTimes(1)
  })

  it('marks one day from the keyboard', () => {
    const { onPaint, onStroke, second } = setup()
    fireEvent.click(second, { detail: 0 })
    expect(onPaint.mock.calls).toEqual([['2026-12-02']])
    expect(onStroke).toHaveBeenCalledTimes(1)
  })
})
