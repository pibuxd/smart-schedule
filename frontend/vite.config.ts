import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

/**
 * The iOS and Android apps (`npm run build:native`, docs/mobile.md) carry the SPA inside the app and call the API
 * at a fixed HTTPS address, read from `.env.native.local` (copied from `.env.native.example`, never committed).
 */
function checkNativeApiOrigin(mode: string) {
  if (mode !== 'native') return
  const origin = loadEnv(mode, process.cwd(), 'VITE_').VITE_API_ORIGIN ?? ''
  let url: URL | null = null
  try {
    url = new URL(origin)
  } catch {
    url = null
  }
  if (!url || url.protocol !== 'https:' || url.pathname !== '/' || url.hostname.endsWith('.example')) {
    throw new Error(
      'Set VITE_API_ORIGIN in frontend/.env.native.local to the server\'s HTTPS address, e.g. https://grafikomat.pl ' +
        '(see .env.native.example).',
    )
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  checkNativeApiOrigin(mode)
  return {
    plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        // In development Vite forwards the API to Django, the same way Caddy does in Docker.
        '/api': { target: process.env.VITE_API_PROXY ?? 'http://localhost:8000', changeOrigin: false },
      },
    },
  }
})
