import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@fontsource-variable/atkinson-hyperlegible-next'
import './index.css'
import { errorStatus } from './lib/api-error'
import { routeTree } from './routeTree.gen'

/** The session ended (logged out elsewhere, expired): go to the login screen instead of showing errors. */
function onApiError(error: unknown) {
  if (errorStatus(error) !== 401) return
  const path = window.location.pathname
  if (path.startsWith('/logowanie') || path.startsWith('/rejestracja')) return
  queryClient.clear()
  void router.navigate({ to: '/logowanie', replace: true })
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
  queryCache: new QueryCache({ onError: onApiError }),
  mutationCache: new MutationCache({ onError: onApiError }),
})

const router = createRouter({ routeTree, context: { queryClient } })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
