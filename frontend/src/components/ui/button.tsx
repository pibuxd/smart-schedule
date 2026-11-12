import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'

import { cn } from '../../lib/cn'

// shadcn/ui-style button, styled only with the Grafikomat tokens.
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-md border-2 px-5 text-base font-semibold ' +
    'cursor-pointer select-none active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60',
  {
    variants: {
      variant: {
        primary: 'border-accent bg-accent text-accent-ink hover:bg-accent-strong hover:border-accent-strong',
        secondary: 'border-accent bg-surface text-accent hover:bg-accent-soft',
        quiet: 'border-transparent bg-transparent text-accent underline underline-offset-4 hover:bg-accent-soft',
        danger: 'border-cannot bg-surface text-cannot hover:bg-cannot-soft',
      },
      size: {
        main: 'min-h-(--touch-main)',
        normal: 'min-h-(--touch)',
      },
      wide: { true: 'w-full', false: '' },
    },
    defaultVariants: { variant: 'primary', size: 'main', wide: false },
  },
)

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>

export function Button({ className, variant, size, wide, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant, size, wide }), className)} {...props} />
}
