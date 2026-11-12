import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

// tailwind-merge must know our custom font sizes, or it treats `text-hero` as a colour and drops it.
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ['cell', 'xs', 'sm', 'base', 'lg', 'xl', '2xl', 'hero'] } },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
