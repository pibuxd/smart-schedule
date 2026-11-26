import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'

import { useLogout } from '../../api/generated/auth/auth'
import { disablePush } from '../../native/push'

/**
 * Ends the session, forgets everything cached for this person and opens the login screen. In the apps the phone
 * also stops getting push notifications (the server unpins it with the session).
 */
export function useSignOut() {
  const logout = useLogout()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return () =>
    logout.mutate(undefined, {
      onSettled: async () => {
        void disablePush()
        queryClient.clear()
        await navigate({ to: '/logowanie' })
      },
    })
}
