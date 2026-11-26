import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@fontsource-variable/atkinson-hyperlegible-next'
import './index.css'
import { errorStatus, shouldRetry } from './lib/api-error'
import { noteUnauthorized, rememberSession } from './lib/session-ended'
import { getLogoutMutationKey, getMeQueryKey } from './api/generated/auth/auth'
import { openCompany } from './features/auth/session'
import { bootNativeApp } from './native/boot'
import { onPushOpen } from './native/push'
import { routeTree } from './routeTree.gen'

/** The session ended (logged out elsewhere, expired): go to the login screen instead of showing errors. */
function onApiError(error: unknown) {
  if (errorStatus(error) !== 401) return
  const path = window.location.pathname
  if (path.startsWith('/logowanie') || path.startsWith('/rejestracja')) return
  const hadSession = Boolean(queryClient.getQueryData(getMeQueryKey()))
  queryClient.clear()
  noteUnauthorized(hadSession)
  void router.navigate({ to: '/logowanie', replace: true })
}

// After a deploy, an open tab asks for screen files that no longer exist: load the new version instead of failing.
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  window.location.reload()
})

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: shouldRetry, refetchOnWindowFocus: false } },
  queryCache: new QueryCache({
    onError: onApiError,
    onSuccess: (_, query) => { if (query.queryKey[0] === getMeQueryKey()[0]) rememberSession(true) },
  }),
  mutationCache: new MutationCache({
    onError: onApiError,
    onSuccess: (_data, _vars, _result, mutation) => {
      if (mutation.options.mutationKey?.[0] === getLogoutMutationKey()[0]) rememberSession(false)
    },
  }),
})

const router = createRouter({ routeTree, context: { queryClient } })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

async function start() {
  // The iOS and Android apps: stored login and push listeners first (nothing in a browser).
  await bootNativeApp(() => void queryClient.invalidateQueries())
  // A tapped push notification opens its shift or period, in the company it is about.
  onPushOpen(({ path, companyId }) => {
    if (companyId) openCompany(companyId)
    void router.history.push(path)
  })
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  )
}

void start()
