import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

/** Render a screen inside a router and a fresh query client (components use <Link> and API hooks). */
export function renderScreen(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <>{ui}</> })
  const other = [
    '/kiedy-moge',
    '/grafik',
    '/zaproszenia',
    '/logowanie',
    '/kierownik',
    '/kierownik/grupa/$groupId/zasady',
    '/kierownik/lokal/$locationId/dyspozycje',
    '/kierownik/lokal/$locationId/pracownicy',
    '/kierownik/lokal/$locationId/ustawienia',
    '/kierownik/lokal/$locationId/zasady',
    '/kierownik/lokal/$locationId/grafik',
    '/kierownik/godziny',
    '/kierownik/oddane-zmiany',
    '/powiadomienia',
    '/kierownik/dostep',
    '/rejestracja',
  ].map((path) =>
    createRoute({ getParentRoute: () => root, path, component: () => null }),
  )
  const router = createRouter({
    routeTree: root.addChildren([page, ...other]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

export type Call = { url: string; method: string; body: unknown }

/** Replace fetch with a table of answers: `route(method, path) -> [status, body]`. Records every call. */
export function mockApi(answer: (method: string, path: string, body: unknown) => [number, unknown]) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? 'GET').toUpperCase()
      const body = init.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ url, method, body })
      const [status, data] = answer(method, url.split('?')[0], body)
      return new Response(status === 204 ? null : JSON.stringify(data), { status })
    }),
  )
  return calls
}
