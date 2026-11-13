import { createFileRoute } from '@tanstack/react-router'

import { OffersScreen } from '../../features/manager/OffersScreen'

export const Route = createFileRoute('/kierownik/oddane-zmiany')({
  component: () => <OffersScreen />,
})
