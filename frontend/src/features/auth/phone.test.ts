import { describe, expect, it } from 'vitest'

import { isE164, OTHER_COUNTRY, phoneProblem, phoneToSend, prettyPhone } from './phone'

describe('phone numbers', () => {
  it('puts the picked country in front of the typed digits', () => {
    expect(phoneToSend('PL', '512 345 678')).toBe('+48512345678')
    expect(phoneToSend('PL', '48 512-345-678')).toBe('+48512345678')
    expect(phoneToSend('UA', '50 123 45 67')).toBe('+380501234567')
    // The national 0 people write in their own country stays: the server knows where to drop it.
    expect(phoneToSend('UA', '050 123 45 67')).toBe('+3800501234567')
    expect(phoneToSend(OTHER_COUNTRY, '1 202 555 0123')).toBe('+12025550123')
  })

  it('takes a number typed with + or 00 whole, whatever country is picked', () => {
    expect(phoneToSend('PL', '+380 50 123 4567')).toBe('+380501234567')
    expect(phoneToSend('PL', '0048 512 345 678')).toBe('+48512345678')
    expect(phoneToSend('UA', '+48 512 345 678')).toBe('+48512345678')
  })

  it('asks for 9 digits of a Polish number and for a whole number elsewhere', () => {
    expect(phoneProblem('PL', '12 34')).toMatch(/Wpisz 9 cyfr/)
    expect(phoneProblem('PL', '512 345 678')).toBeNull()
    expect(phoneProblem('PL', 'abc')).toBe('Wpisz same cyfry numeru.')
    expect(phoneProblem('UA', '50 12')).toBe('Wpisz cały numer telefonu.')
    expect(phoneProblem('UA', '50 123 4567')).toBeNull()
  })

  it('writes stored numbers with the country code apart', () => {
    expect(prettyPhone('+48512345678')).toBe('+48 512 345 678')
    expect(prettyPhone('+380501234567')).toBe('+380 501 234 567')
    expect(prettyPhone('+4915123456789')).toBe('+49 151 234 567 89')
    expect(prettyPhone('+447400123456')).toBe('+44 740 012 3456')
    expect(prettyPhone('512 345 678')).toBe('512 345 678')
    expect(isE164('+380501234567')).toBe(true)
    expect(isE164('050 123 4567')).toBe(false)
  })
})
