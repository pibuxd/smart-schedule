import { createFileRoute } from '@tanstack/react-router'

import { OverviewScreen } from '../../features/manager/OverviewScreen'

export const Route = createFileRoute('/kierownik/')({
  component: () => <OverviewScreen />,
})
