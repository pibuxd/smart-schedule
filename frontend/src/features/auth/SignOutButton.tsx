import { cn } from '../../lib/cn'
import { useSignOut } from './sign-out'

/** "Wyloguj" for screens without the employee's or the manager's header (invitations, a new company). */
export function SignOutButton({ className }: { className?: string }) {
  const signOut = useSignOut()
  return (
    <button
      type="button"
      onClick={signOut}
      className={cn(
        'min-h-(--touch) shrink-0 cursor-pointer rounded-sm px-2 font-semibold text-accent underline underline-offset-4 hover:bg-accent-soft',
        className,
      )}
    >
      Wyloguj
    </button>
  )
}
