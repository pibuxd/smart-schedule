/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The iOS and Android apps only: the server's HTTPS address, e.g. "https://grafikomat.pl" (docs/mobile.md). */
  readonly VITE_API_ORIGIN?: string
}
