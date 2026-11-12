import { createFileRoute } from '@tanstack/react-router'

import { SystemStatus } from '../components/SystemStatus'

export const Route = createFileRoute('/')({
  component: HomePage,
})

function HomePage() {
  return (
    <main className="mx-auto max-w-xl p-6">
      <h1 className="text-3xl font-semibold">Grafikomat</h1>
      <p className="mt-2 text-lg">Szkielet aplikacji. Ekrany pojawią się w kolejnych etapach.</p>
      <SystemStatus />
    </main>
  )
}
