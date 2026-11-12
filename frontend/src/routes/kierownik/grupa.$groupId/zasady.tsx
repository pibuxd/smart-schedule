import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'

import { RulesScreen } from '../../../features/manager/RulesScreen'

export const Route = createFileRoute('/kierownik/grupa/$groupId/zasady')({
  component: Page,
})

function Page() {
  const { groupId } = Route.useParams()
  return (
    <div className="grid gap-4">
      <Link
        to="/kierownik"
        className="inline-flex min-h-(--touch) w-fit items-center gap-1.5 font-semibold text-accent underline underline-offset-4"
      >
        <ArrowLeft aria-hidden="true" size={20} />
        Wszystkie lokale
      </Link>
      <RulesScreen scope="group" scopeId={groupId} />
    </div>
  )
}
