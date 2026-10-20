/**
 * HomePilot page structure and surfaces (see ./README.md): the page shell, its header, cards,
 * stat tiles, status badges, switches, notices and empty states. Every page composes these,
 * so a person moving from Meetings to Routines to Models sees one product.
 */
import React from 'react'
import { AlertTriangle, CheckCircle2, Info, XCircle, type LucideIcon } from 'lucide-react'

type IconType = LucideIcon

// ── page ─────────────────────────────────────────────────────────────────────

/** The scrolling page: near-black canvas, shared width and gutters. */
export function Page({ children, width = 'default', className = '' }: {
  children: React.ReactNode
  /** `default` 72rem for dashboards and lists; `narrow` 48rem for forms and reading. */
  width?: 'default' | 'narrow' | 'full'
  className?: string
}) {
  const max = width === 'narrow' ? 'max-w-3xl' : width === 'full' ? 'max-w-none' : 'max-w-6xl'
  return (
    <div className="h-full overflow-y-auto bg-hp-canvas text-white">
      <div className={`mx-auto ${max} px-4 pb-12 pt-6 sm:px-6 sm:pt-8 lg:px-8 ${className}`}>{children}</div>
    </div>
  )
}

/**
 * The page header: a small eyebrow (icon + context), the title, a readable but secondary
 * description, and the page's actions on the right (below on phones).
 */
export function PageHeader({ eyebrow, eyebrowIcon: EyebrowIcon, title, description, actions }: {
  eyebrow?: string
  eyebrowIcon?: IconType
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow ? (
          <div className="hp-clear-nav flex items-center gap-2 text-sm text-white/55">
            {EyebrowIcon ? <EyebrowIcon size={16} className="text-hp-accent-fg" aria-hidden /> : null}
            {eyebrow}
          </div>
        ) : null}
        <h1 className={`${eyebrow ? 'mt-2' : 'hp-clear-nav'} text-3xl font-semibold tracking-tight text-white`}>{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-[15px] leading-6 text-white/55">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}

// ── surfaces ─────────────────────────────────────────────────────────────────

export const CARD = 'rounded-card border border-white/10 bg-white/[0.02]'

/** A content card, optionally with a titled header row (icon · title · action). */
export function Card({ title, icon: Icon, action, children, className = '', padded = true, as: Tag = 'section' }: {
  title?: React.ReactNode
  icon?: IconType
  action?: React.ReactNode
  children?: React.ReactNode
  className?: string
  padded?: boolean
  as?: 'section' | 'article' | 'div'
}) {
  return (
    <Tag className={`${CARD} ${padded ? 'p-4 sm:p-5' : ''} ${className}`}>
      {title ? (
        <div className="mb-3 flex items-center gap-2">
          {Icon ? <Icon size={18} className="shrink-0 text-hp-accent-fg" aria-hidden /> : null}
          <h3 className="flex-1 font-semibold text-white">{title}</h3>
          {action}
        </div>
      ) : null}
      {children}
    </Tag>
  )
}

/** The violet-tinted square that holds an icon in tiles, rows and headers. */
export function IconTile({ icon: Icon, size = 'md', className = '' }: { icon: IconType; size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const box = size === 'sm' ? 'h-9 w-9 rounded-lg' : size === 'lg' ? 'h-12 w-12 rounded-2xl' : 'h-11 w-11 rounded-xl'
  return (
    <span className={`grid shrink-0 place-items-center border border-violet-400/20 bg-hp-accent/15 text-hp-accent-fg ${box} ${className}`} aria-hidden>
      <Icon size={size === 'sm' ? 16 : size === 'lg' ? 22 : 20} />
    </span>
  )
}

/** A number (or short value) with its label and a caption — the tiles on top of a page. */
export function StatTile({ icon, label, value, caption, className = '' }: {
  icon: IconType
  label: string
  value: React.ReactNode
  caption?: React.ReactNode
  className?: string
}) {
  return (
    <div className={`${CARD} flex items-center gap-3 p-3.5 sm:gap-4 sm:p-4 ${className}`}>
      <IconTile icon={icon} />
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/45">{label}</div>
        <div className="mt-0.5 truncate text-xl font-semibold leading-7 text-white">{value}</div>
        {caption ? <div className="truncate text-xs text-white/50">{caption}</div> : null}
      </div>
    </div>
  )
}

// ── status ───────────────────────────────────────────────────────────────────

export type Tone = 'violet' | 'blue' | 'indigo' | 'teal' | 'green' | 'amber' | 'red' | 'slate' | 'pink' | 'sky'

/** Badge colours by meaning. Meetings' status chips use the same table (library/format.ts). */
export const TONE_CLASSES: Record<Tone, string> = {
  violet: 'bg-violet-500/15 text-violet-200 border-violet-400/25',
  blue: 'bg-blue-500/15 text-blue-200 border-blue-400/25',
  indigo: 'bg-indigo-500/20 text-indigo-200 border-indigo-400/25',
  teal: 'bg-teal-500/15 text-teal-200 border-teal-400/25',
  green: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/25',
  amber: 'bg-amber-500/15 text-amber-200 border-amber-400/30',
  red: 'bg-rose-500/15 text-rose-300 border-rose-400/30',
  slate: 'bg-white/[0.06] text-white/70 border-white/10',
  pink: 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-400/25',
  sky: 'bg-sky-500/15 text-sky-200 border-sky-400/25',
}

/** A small status badge: Active, Paused, Completed, Failed… `busy` adds a pulsing dot. */
export function StatusBadge({ tone, children, busy = false, title }: {
  tone: Tone
  children: React.ReactNode
  busy?: boolean
  title?: string
}) {
  return (
    <span title={title} className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${busy ? 'animate-pulse' : ''}`} aria-hidden />
      {children}
    </span>
  )
}

/** One switch for the whole product: `role="switch"`, violet when on. */
export function Switch({ checked, onChange, label, disabled = false, size = 'md' }: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
  size?: 'sm' | 'md'
}) {
  const track = size === 'sm' ? 'h-5 w-9' : 'h-6 w-11'
  const knob = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'
  const shift = size === 'sm' ? (checked ? 'translate-x-[18px]' : 'translate-x-[3px]') : checked ? 'translate-x-6' : 'translate-x-1'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[
        'relative inline-flex shrink-0 items-center rounded-full transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-hp-accent-fg/70 disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-hp-accent' : 'bg-white/15',
        track,
      ].join(' ')}
    >
      <span className={`inline-block rounded-full bg-white shadow transition-transform ${knob} ${shift}`} />
    </button>
  )
}

// ── notices ──────────────────────────────────────────────────────────────────

export type AlertTone = 'info' | 'success' | 'warning' | 'danger'

const ALERT: Record<AlertTone, { box: string; icon: string; Icon: IconType; role: 'status' | 'alert' }> = {
  info: { box: 'border-sky-400/20 bg-sky-500/[0.06] text-sky-50/85', icon: 'text-sky-300', Icon: Info, role: 'status' },
  success: { box: 'border-emerald-400/20 bg-emerald-500/[0.06] text-emerald-50/85', icon: 'text-emerald-300', Icon: CheckCircle2, role: 'status' },
  warning: { box: 'border-amber-400/25 bg-amber-500/[0.07] text-amber-50/85', icon: 'text-amber-300', Icon: AlertTriangle, role: 'status' },
  danger: { box: 'border-rose-400/30 bg-rose-500/10 text-rose-50/90', icon: 'text-rose-300', Icon: XCircle, role: 'alert' },
}

/** A compact notice in a page: what is going on, in one or two lines, and what to do. */
export function InlineAlert({ tone, title, children, icon, action, className = '' }: {
  tone: AlertTone
  title?: React.ReactNode
  children?: React.ReactNode
  icon?: IconType
  action?: React.ReactNode
  className?: string
}) {
  const style = ALERT[tone]
  const Icon = icon || style.Icon
  return (
    <div role={style.role} className={`flex items-start gap-3 rounded-card border px-4 py-3 text-sm leading-6 ${style.box} ${className}`}>
      <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-white/[0.06]" aria-hidden>
        <Icon size={14} className={style.icon} />
      </span>
      <div className="min-w-0 flex-1">
        {title ? <strong className="font-semibold text-white">{title} </strong> : null}
        <span className="text-white/70">{children}</span>
      </div>
      {action ? <div className="shrink-0 self-center">{action}</div> : null}
    </div>
  )
}

/**
 * An empty list, made to look intentional: a soft violet glow, one icon, what this is for, and
 * the way to start. `art` replaces the plain icon tile with a richer mark.
 */
export function EmptyState({ icon, art, title, children, action, className = '' }: {
  icon?: IconType
  art?: React.ReactNode
  title: string
  children?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-card border border-white/10 px-6 py-14 text-center sm:py-16 ${className}`}
      style={{ background: 'radial-gradient(60% 70% at 50% 35%, rgb(var(--hp-accent) / 0.16), transparent 70%), rgb(255 255 255 / 0.015)' }}
    >
      <div className="mx-auto grid place-items-center">{art || (icon ? <IconTile icon={icon} size="lg" /> : null)}</div>
      <h2 className="mt-5 text-xl font-semibold text-white">{title}</h2>
      {children ? <p className="mx-auto mt-2 max-w-md text-[15px] leading-6 text-white/55">{children}</p> : null}
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  )
}

/** Placeholder rows while a list loads: the same shape as the content, no layout jump. */
export function SkeletonRows({ count = 3, height = 'h-28', label = 'Loading' }: { count?: number; height?: string; label?: string }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label={label} role="status">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={`${height} animate-pulse rounded-card border border-white/[0.06] bg-white/[0.03]`} />
      ))}
    </div>
  )
}
