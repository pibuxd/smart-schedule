// App icons and launch screens for the iOS and Android apps (docs/mobile.md), drawn from the Wordmark mark
// (src/components/Wordmark.tsx): a sheet of squared paper with a blue header line on the paper colour.
// Run after changing the mark: `npm run app:icons`. The PNGs are committed, so only this needs Playwright, which is
// not a dependency of the project: it is taken from a global install (`npm install -g playwright`).
import { mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const { chromium } = createRequire(import.meta.url)('playwright')

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PAPER = '#f3f5f1'
const ACCENT = '#1e44b8'
const SURFACE = '#ffffff'

/** The mark in a 28×28 box, as in Wordmark.tsx. */
const MARK = `
  <rect x="1" y="1" width="26" height="26" rx="6" fill="${SURFACE}" stroke="${ACCENT}" stroke-width="2"/>
  <rect x="1" y="1" width="26" height="8" rx="6" fill="${ACCENT}"/>
  <rect x="1" y="5" width="26" height="4" fill="${ACCENT}"/>
  <path d="M10 9v18M19 9v18M1 18h26" stroke="${ACCENT}" stroke-width="1.5"/>`

/** An SVG of width×height with the mark centred, `share` of the shorter side wide. */
function svg({ width, height, share, background = PAPER, shape = 'square' }) {
  const side = Math.min(width, height) * share
  const scale = side / 28
  const x = (width - side) / 2
  const y = (height - side) / 2
  const bg =
    background === null
      ? ''
      : shape === 'circle'
        ? `<circle cx="${width / 2}" cy="${height / 2}" r="${width / 2}" fill="${background}"/>`
        : shape === 'rounded'
          ? `<rect width="${width}" height="${height}" rx="${width * 0.2}" fill="${background}"/>`
          : `<rect width="${width}" height="${height}" fill="${background}"/>`
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    ${bg}<g transform="translate(${x} ${y}) scale(${scale})">${MARK}</g></svg>`
}

const android = (dir) => resolve(root, 'android/app/src/main/res', dir)
const ios = (file) => resolve(root, 'ios/App/App/Assets.xcassets', file)

const DENSITIES = { mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 }
const jobs = []
for (const [name, k] of Object.entries(DENSITIES)) {
  const launcher = 48 * k
  // Before Android 8: the whole icon, square with rounded corners and round.
  jobs.push({ file: android(`mipmap-${name}/ic_launcher.png`), width: launcher, height: launcher, share: 0.62, shape: 'rounded', transparent: true })
  jobs.push({ file: android(`mipmap-${name}/ic_launcher_round.png`), width: launcher, height: launcher, share: 0.56, shape: 'circle', transparent: true })
  // Android 8+: the foreground layer (108 dp, only the middle 66 dp is always visible) on a paper background colour.
  const layer = 108 * k
  jobs.push({ file: android(`mipmap-${name}/ic_launcher_foreground.png`), width: layer, height: layer, share: 0.44, background: null, transparent: true })
}
const SPLASH = { mdpi: [320, 480], hdpi: [480, 800], xhdpi: [720, 1280], xxhdpi: [960, 1600], xxxhdpi: [1280, 1920] }
for (const [name, [w, h]] of Object.entries(SPLASH)) {
  jobs.push({ file: android(`drawable-port-${name}/splash.png`), width: w, height: h, share: 0.22 })
  jobs.push({ file: android(`drawable-land-${name}/splash.png`), width: h, height: w, share: 0.22 })
}
jobs.push({ file: android('drawable/splash.png'), width: 480, height: 320, share: 0.22 })
// iOS: one 1024 px icon without transparency (iOS rounds the corners itself), and the launch image.
jobs.push({ file: ios('AppIcon.appiconset/AppIcon-512@2x.png'), width: 1024, height: 1024, share: 0.6 })
// Store listing: Google Play wants a 512 px icon without transparency (App Store takes the app's own).
jobs.push({ file: resolve(root, 'store/google-play-icon-512.png'), width: 512, height: 512, share: 0.6 })
for (const suffix of ['', '-1', '-2']) {
  jobs.push({ file: ios(`Splash.imageset/splash-2732x2732${suffix}.png`), width: 2732, height: 2732, share: 0.12 })
}

const browser = await chromium.launch()
const page = await browser.newPage({ deviceScaleFactor: 1 })
for (const job of jobs) {
  await page.setViewportSize({ width: job.width, height: job.height })
  await page.setContent(`<html><body style="margin:0;background:transparent">${svg(job)}</body></html>`)
  mkdirSync(dirname(job.file), { recursive: true })
  await page.locator('svg').screenshot({ path: job.file, omitBackground: Boolean(job.transparent) })
}
await browser.close()
console.log(`${jobs.length} images written`)
