import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SystemStatus } from './SystemStatus'

function renderWithQuery() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SystemStatus />
    </QueryClientProvider>,
  )
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  )
}

describe('SystemStatus', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says the server works when the API is healthy', async () => {
    mockFetch(200, { status: 'ok', database: 'ok' })
    renderWithQuery()
    expect(await screen.findByText('Serwer i baza danych działają.')).toBeInTheDocument()
  })

  it('shows a human error message when the API is down', async () => {
    mockFetch(503, { status: 'error', database: 'unavailable' })
    renderWithQuery()
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się połączyć z serwerem')
  })
})
