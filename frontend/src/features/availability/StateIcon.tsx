import type { AvailabilityState } from './marks'

/** The sign of each availability state: a cross, a dash, a ring, a tick. Drawn, never an emoji. */
export function StateIcon({ state, size = 20 }: { state: AvailabilityState; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor">
      {state === 'cannot' && <path d="M6 6l12 12M18 6L6 18" strokeWidth="3" strokeLinecap="round" />}
      {state === 'prefer_not' && <path d="M6 12h12" strokeWidth="3" strokeLinecap="round" />}
      {state === 'neutral' && <circle cx="12" cy="12" r="6" strokeWidth="2.5" />}
      {state === 'prefer' && (
        <path d="M5 12.5l4.5 4.5L19 7.5" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  )
}
