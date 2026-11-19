import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { Section } from './field'

test('the description of a section shows only after pressing the "i" button', () => {
  render(
    <Section title="Obsada" description="Ile osób potrzeba.">
      <p>treść</p>
    </Section>,
  )
  expect(screen.queryByText('Ile osób potrzeba.')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Wyjaśnij: Obsada' }))
  expect(screen.getByText('Ile osób potrzeba.')).toBeVisible()
})

test('a collapsible section starts closed, with its heading in view', () => {
  render(
    <Section title="Zmienione po terminie (1)" collapsible>
      <p>Anna: 2 dni</p>
    </Section>,
  )
  const details = screen.getByRole('group')
  expect(details).not.toHaveAttribute('open')
  expect(screen.getByRole('heading', { name: 'Zmienione po terminie (1)' })).toBeInTheDocument()
})
