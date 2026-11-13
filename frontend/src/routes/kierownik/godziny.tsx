import { createFileRoute } from '@tanstack/react-router'

import { HoursScreen } from '../../features/manager/HoursScreen'

export const Route = createFileRoute('/kierownik/godziny')({
  component: () => <HoursScreen />,
})
