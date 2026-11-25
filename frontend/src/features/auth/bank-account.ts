/** "61109010140000071219812874" -> "61 1090 1014 0000 0712 1981 2874" (how banks print it). */
export function prettyBankAccount(digits: string): string {
  if (!digits) return ''
  const groups = [digits.slice(0, 2)]
  for (let i = 2; i < digits.length; i += 4) groups.push(digits.slice(i, i + 4))
  return groups.join(' ')
}

/** What was typed, the way the server keeps it: no spaces, dashes or "PL" (the server checks the digits). */
export function bankAccountDigits(typed: string): string {
  return typed.replace(/[\s-]/g, '').replace(/^pl/i, '')
}
