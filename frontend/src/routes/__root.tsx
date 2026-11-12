import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  notFoundComponent: NotFound,
})

function RootLayout() {
  return (
    <div className="min-h-dvh bg-paper text-ink">
      <Outlet />
    </div>
  )
}

function NotFound() {
  return (
    <main className="mx-auto grid max-w-(--column) gap-3 px-4 py-10">
      <h1 className="m-0 text-xl font-extrabold">Nie ma takiej strony</h1>
      <Link to="/" className="font-semibold text-accent underline underline-offset-4">
        Przejdź do swojego grafiku
      </Link>
    </main>
  )
}
