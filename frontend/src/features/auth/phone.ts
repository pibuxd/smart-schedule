/** "+48512345678" -> "+48 512 345 678" */
export function prettyPhone(e164: string): string {
  const digits = e164.replace(/^\+48/, '')
  return `+48 ${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`
}
