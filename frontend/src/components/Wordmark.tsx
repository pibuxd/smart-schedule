/** The name of the app with a small mark: a sheet of squared paper with a blue header line. */
export function Wordmark() {
  return (
    <div className="flex items-center gap-2.5 text-lg font-extrabold">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <rect x="1" y="1" width="26" height="26" rx="6" className="fill-surface stroke-accent" strokeWidth="2" />
        <rect x="1" y="1" width="26" height="8" rx="6" className="fill-accent" />
        <rect x="1" y="5" width="26" height="4" className="fill-accent" />
        <path d="M10 9v18M19 9v18M1 18h26" className="stroke-accent" strokeWidth="1.5" />
      </svg>
      Grafikomat
    </div>
  )
}
