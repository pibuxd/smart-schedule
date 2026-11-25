/** The number the way the server keeps it: as written, any bank, with runs of spaces made one (Piotr, 25.11.2026). */
export function tidyBankAccount(typed: string): string {
  return typed.trim().split(/\s+/).filter(Boolean).join(' ')
}
