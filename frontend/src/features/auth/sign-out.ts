import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'

import { useLogout } from '../../api/generated/auth/auth'
import { errorStatus } from '../../lib/api-error'
import { disablePush } from '../../native/push'

export type SignOut = {
  /** "Wyloguj": ask the server to end the session. */
  run: () => void
  pending: boolean
  /** The server did not confirm (no network, a server error): the session goes on, so the screen says so. */
  failed: boolean
  dismiss: () => void
}

/**
 * Ends the session, forgets everything cached for this person and opens the login screen. In the apps the phone
 * also stops getting push notifications (the server unpins it with the session). Only a confirmed logout does
 * that: when the request fails, the session key stays in the app (and the cookie in a browser), so the person
 * stays logged in, sees it (`SignOutFailed`) and can try again.
 */
export function useSignOut(): SignOut {
  const logout = useLogout()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const finish = async () => {
    void disablePush()
    queryClient.clear()
    await navigate({ to: '/logowanie' })
  }
  return {
    run: () => {
      if (logout.isPending) return
      logout.mutate(undefined, {
        onSuccess: finish,
        // 401: the session had ended already, so this is a logout too.
        onError: (error) => {
          if (errorStatus(error) === 401) void finish()
        },
      })
    },
    pending: logout.isPending,
    failed: logout.isError && errorStatus(logout.error) !== 401,
    dismiss: () => logout.reset(),
  }
}
