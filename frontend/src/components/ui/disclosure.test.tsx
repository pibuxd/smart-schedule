import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { Disclosure } from './disclosure'
import { Section } from './field'

test('a fold starts closed, shows a chevron and opens when its line is pressed', () => {
  const { container } = render(
    <Disclosure summary="Historia tej zmiany (2)">
      <p>Anna → Marek</p>
    </Disclosure>,
  )
  const details = screen.getByRole('group')
  expect(details).not.toHaveAttribute('open')
  expect(container.querySelector('summary svg')).not.toBeNull()
  fireEvent.click(screen.getByText('Historia tej zmiany (2)'))
  expect(details).toHaveAttribute('open')
})

test('a fold can start open', () => {
  render(
    <Disclosure summary="Doświadczeni i inne godziny" open>
      <p>pola</p>
    </Disclosure>,
  )
  expect(screen.getByRole('group')).toHaveAttribute('open')
})

test('a folded section shows its status next to the heading while closed', () => {
  render(
    <Section title="Jak grafik trzyma się zasad" collapsible status="2 złamane">
      <p>lista</p>
    </Section>,
  )
  const summary = screen.getByRole('heading', { name: 'Jak grafik trzyma się zasad' }).closest('summary')
  expect(summary).toHaveTextContent('2 złamane')
  expect(screen.getByRole('group')).not.toHaveAttribute('open')
})

test('every fold in the app uses Disclosure, so each one has the chevron and the hover tint', () => {
  const sources = import.meta.glob<string>(['../../**/*.tsx', '!../../**/*.test.tsx', '!./disclosure.tsx'], {
    query: '?raw',
    import: 'default',
    eager: true,
  })
  expect(Object.keys(sources).length).toBeGreaterThan(20)
  const bare = Object.entries(sources)
    .filter(([, text]) => /<details[\s>]/.test(text))
    .map(([path]) => path)
  expect(bare).toEqual([])
})
