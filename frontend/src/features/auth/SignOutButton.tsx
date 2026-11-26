import { cn } from '../../lib/cn'
import { type SignOut, useSignOut } from './sign-out'

/** "Wyloguj" for screens without the employee's or the manager's header (invitations, a new company). */
export function SignOutButton({ className }: { className?: string }) {
  const signOut = useSignOut()
  return (
    <>
      <button
        type="button"
        onClick={signOut.run}
        className={cn(
          'min-h-(--touch) shrink-0 cursor-pointer rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft',
          className,
        )}
      >
        Wyloguj
      </button>
      <SignOutFailed signOut={signOut} />
    </>
  )
}

const BAR_BUTTON = 'min-h-(--touch) cursor-pointer rounded-sm px-2 font-semibold underline underline-offset-4'

/**
 * Logging out did not reach the server: the session goes on (in the apps the phone keeps its login and its push
 * notifications), so say so at the top of the screen and offer to try again.
 */
export function SignOutFailed({ signOut }: { signOut: SignOut }) {
  if (!signOut.failed) return null
  return (
    <div className="fixed inset-x-0 top-[env(safe-area-inset-top)] z-50 px-4 pt-2">
      <div
        role="alert"
        className="mx-auto flex max-w-(--column) flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-cannot bg-cannot-soft px-3 py-2 text-cannot shadow-chat"
      >
        <p className="m-0 min-w-0 flex-1">Nie udało się wylogować. Sesja trwa dalej. Sprawdź internet.</p>
        <span className="flex shrink-0 items-center">
          <button type="button" onClick={signOut.run} disabled={signOut.pending} className={BAR_BUTTON}>
            Wyloguj jeszcze raz
          </button>
          <button type="button" onClick={signOut.dismiss} className={cn(BAR_BUTTON, 'text-ink-muted')}>
            Zamknij
          </button>
        </span>
      </div>
    </div>
  )
}
