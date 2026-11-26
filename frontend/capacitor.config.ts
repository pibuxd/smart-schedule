import type { CapacitorConfig } from '@capacitor/cli'

/**
 * The iOS and Android apps (Capacitor). Both carry the SPA built into `dist/` by `npm run build:native` and talk
 * to the Django API over HTTPS at `VITE_API_ORIGIN` (docs/mobile.md). Nothing here is secret.
 */
const config: CapacitorConfig = {
  // The store identifier: fixed for good after the first upload to App Store Connect or Google Play.
  appId: 'pl.grafikomat.app',
  appName: 'Grafikomat',
  webDir: 'dist',
  // The app's own pages come from https://localhost (Android) and capacitor://localhost (iOS); the API lets in
  // exactly these origins (`NATIVE_APP_ORIGINS` in the backend settings).
  server: { androidScheme: 'https' },
  plugins: {
    // A notification that arrives while the app is open is shown too (iOS hides it by default).
    PushNotifications: { presentationOptions: ['banner', 'list', 'sound'] },
    // Light screens: dark status bar icons. The app sets viewport-fit=cover and pads itself (src/native/boot.ts).
    SystemBars: { style: 'LIGHT', insetsHandling: 'css', initialViewportFitValueHint: 'cover' },
  },
}

export default config
