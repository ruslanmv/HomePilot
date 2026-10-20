/**
 * HomePilot buttons — one set of variants for the whole product (see ./README.md).
 *
 *   primary    the page's main action: solid violet (`hp-accent`), one per view
 *   secondary  neutral outline on a faint surface: everything else that matters
 *   ghost      quiet text button for rows of actions (History, Edit…)
 *   danger     destructive, quiet until hovered
 *
 * Sizes follow the Meetings pages: sm 32 px (row actions), md 40 px, lg 44 px (touch-friendly
 * primary). Focus is always visible; disabled is dimmed and not clickable; `loading` keeps the
 * label and swaps the icon for a spinner so the button does not jump.
 */
import React from 'react'
import { Loader2, type LucideIcon } from 'lucide-react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

const BASE =
  'inline-flex items-center justify-center gap-2 font-semibold whitespace-nowrap transition-colors ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-hp-accent-fg/70 focus-visible:ring-offset-0 ' +
  'disabled:cursor-not-allowed disabled:opacity-50'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-hp-accent text-white shadow-lg shadow-violet-950/40 hover:bg-hp-accent-hover',
  secondary: 'border border-white/10 bg-white/[0.04] text-white/85 hover:border-white/20 hover:bg-white/[0.08] hover:text-white',
  ghost: 'text-white/60 hover:bg-white/[0.06] hover:text-white',
  danger: 'text-white/45 hover:bg-rose-500/10 hover:text-rose-200',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 rounded-lg px-2.5 text-xs gap-1.5',
  md: 'h-10 rounded-xl px-4 text-sm',
  lg: 'h-11 rounded-xl px-5 text-sm',
}

const ICON_SIZES: Record<ButtonSize, number> = { sm: 13, md: 16, lg: 16 }

/** The classes alone, for links and other elements that should look like a button. */
export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', extra = ''): string {
  return [BASE, VARIANTS[variant], SIZES[size], extra].filter(Boolean).join(' ')
}

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  /** A lucide icon component, shown before the label. */
  icon?: LucideIcon
  loading?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon: Icon, loading = false, className = '', children, type = 'button', disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? (
        <Loader2 size={ICON_SIZES[size]} className="animate-spin" aria-hidden />
      ) : Icon ? (
        <Icon size={ICON_SIZES[size]} aria-hidden />
      ) : null}
      {children}
    </button>
  )
})

/** A square icon-only button. `label` is required: it is the button's only name. */
export const IconButton = React.forwardRef<
  HTMLButtonElement,
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & {
    label: string
    icon: LucideIcon
    size?: 'sm' | 'md'
  }
>(function IconButton({ label, icon: Icon, size = 'md', className = '', type = 'button', ...rest }, ref) {
  const box = size === 'sm' ? 'h-8 w-8 rounded-lg' : 'h-10 w-10 rounded-xl'
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={[
        'hp-icon-btn grid shrink-0 place-items-center text-white/55 transition-colors hover:bg-white/[0.08] hover:text-white',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-hp-accent-fg/70 disabled:opacity-40',
        box,
        className,
      ].join(' ')}
      {...rest}
    >
      <Icon size={size === 'sm' ? 15 : 18} aria-hidden />
    </button>
  )
})
