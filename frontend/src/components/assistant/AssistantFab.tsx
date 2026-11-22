import { MessageCircle } from 'lucide-react'

import { cn } from '../../lib/cn'

// The name shows only where the side margin of the page has room for it, so the button covers as little as possible:
// the employee's narrow column leaves room from 1024 px, the manager's wide tables (1240 px) from 1600 px.
const WITH_NAME = {
  lg: {
    button: 'lg:right-6 lg:bottom-6 lg:size-auto lg:min-h-(--touch-main) lg:px-5',
    icon: 'lg:size-5',
    name: 'hidden lg:inline',
  },
  wide: {
    button:
      'min-[1600px]:right-6 min-[1600px]:bottom-6 min-[1600px]:size-auto min-[1600px]:min-h-(--touch-main) min-[1600px]:px-5',
    icon: 'min-[1600px]:size-5',
    name: 'hidden min-[1600px]:inline',
  },
}

/**
 * The assistant's button, always in the bottom right corner after login: a round icon (its name for screen readers
 * and as a tooltip), with the name written out on a wide screen. It floats over the page, so a layout that shows it
 * leaves room for it at the bottom.
 */
export function AssistantFab({
  label = 'Asystent',
  nameFrom = 'lg',
  onClick,
  className,
}: {
  label?: string
  nameFrom?: keyof typeof WITH_NAME
  onClick: () => void
  className?: string
}) {
  const wide = WITH_NAME[nameFrom]
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        'fixed right-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-30 inline-flex size-14 cursor-pointer items-center justify-center gap-2',
        'rounded-full border-2 border-accent bg-accent text-base font-semibold text-accent-ink shadow-fab',
        'select-none hover:border-accent-strong hover:bg-accent-strong active:translate-y-px',
        wide.button,
        className,
      )}
    >
      <MessageCircle aria-hidden="true" size={26} className={wide.icon} />
      <span className={wide.name}>{label}</span>
    </button>
  )
}
