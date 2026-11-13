import { createFileRoute } from '@tanstack/react-router'

import { AccessScreen } from '../../features/manager/AccessScreen'

export const Route = createFileRoute('/kierownik/dostep')({
  component: AccessScreen,
})
