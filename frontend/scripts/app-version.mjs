// Version of the iOS and Android apps (docs/mobile.md): `npm run app:version -- 1.0.1 7`.
// The first number is what the stores show (versionName / CFBundleShortVersionString); the second must grow with
// every build sent to TestFlight or Google Play (versionCode / CFBundleVersion).
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const [version, build] = process.argv.slice(2)
if (!/^\d+\.\d+\.\d+$/.test(version ?? '') || !/^[1-9]\d{0,8}$/.test(build ?? '')) {
  console.error('Usage: npm run app:version -- <x.y.z> <build number>')
  process.exit(1)
}

function rewrite(path, replacements) {
  const file = resolve(root, path)
  let text = readFileSync(file, 'utf8')
  for (const [pattern, value] of replacements) {
    if (!pattern.test(text)) throw new Error(`${path}: ${pattern} not found`)
    text = text.replace(pattern, value)
  }
  writeFileSync(file, text)
}

rewrite('android/gradle.properties', [
  [/^grafikomatVersionName=.*$/m, `grafikomatVersionName=${version}`],
  [/^grafikomatVersionCode=.*$/m, `grafikomatVersionCode=${build}`],
])
rewrite('ios/App/App.xcodeproj/project.pbxproj', [
  [/MARKETING_VERSION = [^;]+;/g, `MARKETING_VERSION = ${version};`],
  [/CURRENT_PROJECT_VERSION = [^;]+;/g, `CURRENT_PROJECT_VERSION = ${build};`],
])
console.log(`Apps set to ${version} (${build})`)
