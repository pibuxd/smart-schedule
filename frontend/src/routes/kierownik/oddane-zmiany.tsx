import { createFileRoute } from '@tanstack/react-router'

import { OffersScreen } from '../../features/manager/OffersScreen'
import { searchId } from '../../lib/focus'

export const Route = createFileRoute('/kierownik/oddane-zmiany')({
  // From a push notification: ?oferta=<id> is the given-away shift it is about.
  validateSearch: (search: Record<string, unknown>): { oferta?: string } => ({ oferta: searchId(search.oferta) }),
  component: Page,
})

function Page() {
  const { oferta } = Route.useSearch()
  return <OffersScreen key={oferta} focusOffer={oferta} />
}
