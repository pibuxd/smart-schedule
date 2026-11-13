import type { AvailabilityState } from './marks'

/** The sign of each availability state: a cross, a thin tick ("mogę"), a double tick ("chętnie"). Drawn, never an emoji. */
export function StateIcon({ state, size = 20 }: { state: AvailabilityState; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor">
      {state === 'cannot' && <path d="M6 6l12 12M18 6L6 18" strokeWidth="3" strokeLinecap="round" />}
      {state === 'neutral' && (
        <path d="M5.5 12.5l4.5 4.5L18.5 8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      )}
      {state === 'prefer' && (
        <path
          d="M2 13l4 4 8.5-9.5M10.5 15.5L12 17l9.5-9.5"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  )
}
