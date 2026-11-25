/**
 * Phone numbers. The server stores and returns them in E.164 ("+48512345678", "+380501234567") and checks them
 * (`normalize_phone`); here they are only put together from the country and the typed digits, and written out.
 */

export type PhoneCountry = {
  /** ISO code, the value of the country list. */
  region: string
  name: string
  /** Calling code without "+". */
  code: string
  /** A number of that country after its code, as the placeholder. */
  example: string
}

export const POLAND: PhoneCountry = { region: 'PL', name: 'Polska', code: '48', example: '512 345 678' }

/**
 * Poland first, then Ukraine (most people from abroad in Polish venues), then the rest alphabetically. Anyone else
 * picks "Inny kraj" and writes the number with its code; a number typed with "+" works whatever is picked.
 */
export const PHONE_COUNTRIES: PhoneCountry[] = [
  POLAND,
  { region: 'UA', name: 'Ukraina', code: '380', example: '50 123 4567' },
  { region: 'BY', name: 'Białoruś', code: '375', example: '29 491 19 11' },
  { region: 'CZ', name: 'Czechy', code: '420', example: '601 123 456' },
  { region: 'PH', name: 'Filipiny', code: '63', example: '905 123 4567' },
  { region: 'GE', name: 'Gruzja', code: '995', example: '555 12 34 56' },
  { region: 'IN', name: 'Indie', code: '91', example: '81234 56789' },
  { region: 'KZ', name: 'Kazachstan', code: '7', example: '771 000 9998' },
  { region: 'CO', name: 'Kolumbia', code: '57', example: '321 1234567' },
  { region: 'LT', name: 'Litwa', code: '370', example: '612 34567' },
  { region: 'MD', name: 'Mołdawia', code: '373', example: '621 12 345' },
  { region: 'NP', name: 'Nepal', code: '977', example: '984 1234567' },
  { region: 'DE', name: 'Niemcy', code: '49', example: '1512 3456789' },
  { region: 'RO', name: 'Rumunia', code: '40', example: '712 034 567' },
  { region: 'SK', name: 'Słowacja', code: '421', example: '912 123 456' },
  { region: 'TR', name: 'Turcja', code: '90', example: '501 234 56 78' },
  { region: 'UZ', name: 'Uzbekistan', code: '998', example: '91 234 56 78' },
  { region: 'GB', name: 'Wielka Brytania', code: '44', example: '7400 123456' },
  { region: 'VN', name: 'Wietnam', code: '84', example: '912 345 678' },
]

/** The value of "Inny kraj": the number is typed whole, with "+" and its code. */
export const OTHER_COUNTRY = 'other'

export function phoneCountry(region: string): PhoneCountry | null {
  return PHONE_COUNTRIES.find((c) => c.region === region) ?? null
}

/**
 * The number to send: typed with "+" or "00" it is taken whole (whatever country is picked), otherwise the picked
 * country's code goes in front. A Polish number typed with 48 in front still works ("48 512 345 678").
 */
export function phoneToSend(region: string, typed: string): string {
  const compact = typed.replace(/[\s\-./()]/g, '')
  if (compact.startsWith('+')) return compact
  if (compact.startsWith('00')) return `+${compact.slice(2)}`
  const country = phoneCountry(region)
  if (!country) return `+${compact}`
  if (country === POLAND && /^48\d{9}$/.test(compact)) return `+${compact}`
  return `+${country.code}${compact}`
}

/** What is wrong with a typed number before anything is sent (the server checks the rest), or null. */
export function phoneProblem(region: string, typed: string): string | null {
  const whole = phoneToSend(region, typed)
  if (!/^\+\d+$/.test(whole)) return 'Wpisz same cyfry numeru.'
  if (region === POLAND.region && whole.startsWith('+48') && whole.length !== 12) {
    return 'Wpisz 9 cyfr numeru, na przykład 512 345 678.'
  }
  if (whole.length < 9 || whole.length > 16) return 'Wpisz cały numer telefonu.'
  return null
}

// Every country calling code (ITU), for splitting a stored number into the code and the rest. No code is the
// beginning of another, so the first one that matches is the right one.
const CALLING_CODES = new Set(
  (
    '1 7 20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49 51 52 53 54 55 56 57 58 60 61 62 63 64 65 66 81 82 ' +
    '84 86 90 91 92 93 94 95 98 211 212 213 216 218 220 221 222 223 224 225 226 227 228 229 230 231 232 233 234 ' +
    '235 236 237 238 239 240 241 242 243 244 245 246 247 248 249 250 251 252 253 254 255 256 257 258 260 261 262 ' +
    '263 264 265 266 267 268 269 290 291 297 298 299 350 351 352 353 354 355 356 357 358 359 370 371 372 373 374 ' +
    '375 376 377 378 380 381 382 383 385 386 387 389 420 421 423 500 501 502 503 504 505 506 507 508 509 590 591 ' +
    '592 593 594 595 596 597 598 599 670 672 673 674 675 676 677 678 679 680 681 682 683 685 686 687 688 689 690 ' +
    '691 692 850 852 853 855 856 880 886 960 961 962 963 964 965 966 967 968 970 971 972 973 974 975 976 977 992 ' +
    '993 994 995 996 998'
  ).split(' '),
)

function groups(digits: string): string {
  const parts = digits.match(/\d{1,3}/g) ?? []
  // No lonely last digit: "151 123 456 7" reads better as "151 123 4567".
  if (parts.length > 1 && parts[parts.length - 1].length === 1) parts.splice(-2, 2, parts.slice(-2).join(''))
  return parts.join(' ')
}

/** "+48512345678" -> "+48 512 345 678", "+380501234567" -> "+380 501 234 567". */
export function prettyPhone(e164: string): string {
  if (!/^\+\d{6,15}$/.test(e164)) return e164
  const digits = e164.slice(1)
  const code = [1, 2, 3].map((n) => digits.slice(0, n)).find((c) => CALLING_CODES.has(c))
  if (!code) return e164
  return `+${code} ${groups(digits.slice(code.length))}`
}

/** A stored number (E.164), not a number as someone typed it. */
export function isE164(phone: string): boolean {
  return /^\+\d{7,15}$/.test(phone)
}
