import { useCallback, useRef } from 'react'

/**
 * What a tapped notification is about (a shift, a day, a given-away shift) is outlined and scrolled into view
 * once. Links: "/grafik?dzien=…&oferta=…", "/kierownik/oddane-zmiany?oferta=…" (backend `push_path`).
 */
export const FOCUSED = 'ring-3 ring-accent'

export function useScrollIntoViewOnce(): (element: HTMLElement | null) => void {
  const done = useRef(false)
  return useCallback((element: HTMLElement | null) => {
    if (!element || done.current) return
    done.current = true
    element.scrollIntoView?.({ block: 'center' })
  }, [])
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
const ID = /^[\w-]{1,64}$/

/** `?dzien=2026-12-04` */
export const searchDay = (value: unknown): string | undefined =>
  typeof value === 'string' && ISO_DAY.test(value) ? value : undefined

/** `?oferta=<id>`, `?okres=<id>` */
export const searchId = (value: unknown): string | undefined =>
  typeof value === 'string' && ID.test(value) ? value : undefined
