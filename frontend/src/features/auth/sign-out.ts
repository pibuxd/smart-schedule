import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'

import { useLogout } from '../../api/generated/auth/auth'

/** Ends the session, forgets everything cached for this person and opens the login screen. */
export function useSignOut() {
  const logout = useLogout()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return () =>
    logout.mutate(undefined, {
      onSettled: async () => {
        queryClient.clear()
        await navigate({ to: '/logowanie' })
      },
    })
}
