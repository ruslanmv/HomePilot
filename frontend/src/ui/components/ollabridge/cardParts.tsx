/**
 * Shared building blocks of the OllaBridge Local / Cloud cards: the status
 * pill, the ⋯ connection menu, field labels, the model dropdown and the
 * gradient Fetch Models button. Tailwind + lucide only, dark theme.
 */
import React, { useEffect, useId, useRef, useState } from 'react'
import { AlertCircle, Box, Info, Loader2, MoreHorizontal, RefreshCw } from 'lucide-react'
import type { ConnStatus } from './useReconnect'

// ── Status pill ──────────────────────────────────────────────────────────────

export function StatusPill({ status }: { status: ConnStatus }) {
  const base = 'inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full border whitespace-nowrap'
  let body: React.ReactNode
  if (status === 'connected') {
    body = (
      <span className={`${base} bg-emerald-500/10 border-emerald-500/30 text-emerald-300`}>
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" aria-hidden /> Connected
      </span>
    )
  } else if (status === 'connecting') {
    body = (
      <span className={`${base} bg-cyan-500/10 border-cyan-500/25 text-cyan-200`}>
        <Loader2 size={11} className="animate-spin" aria-hidden /> Connecting…
      </span>
    )
  } else if (status === 'lost') {
    body = (
      <span className={`${base} bg-amber-500/10 border-amber-500/30 text-amber-300`}>
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" aria-hidden /> Connection lost
      </span>
    )
  } else {
    body = (
      <span className={`${base} bg-rose-500/10 border-rose-500/30 text-rose-300`}>
        <span className="w-1.5 h-1.5 rounded-full bg-rose-400" aria-hidden /> Not Connected
      </span>
    )
  }
  return <span role="status" aria-live="polite">{body}</span>
}

// ── ⋯ connection menu ────────────────────────────────────────────────────────

export interface MenuItem {
  id: string
  label: string
  icon?: React.ReactNode
  onSelect?: () => void
  href?: string
  danger?: boolean
}

export function OverflowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const itemRefs = useRef<Array<HTMLElement | null>>([])
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    // Move focus into the menu so arrow keys work right away.
    const t = setTimeout(() => itemRefs.current[0]?.focus(), 0)
    return () => {
      document.removeEventListener('mousedown', onDown)
      clearTimeout(t)
    }
  }, [open])

  const close = (refocus = true) => {
    setOpen(false)
    if (refocus) buttonRef.current?.focus()
  }

  const onMenuKey = (e: React.KeyboardEvent) => {
    const els = itemRefs.current.filter(Boolean) as HTMLElement[]
    const i = els.indexOf(document.activeElement as HTMLElement)
    if (e.key === 'Escape') { e.preventDefault(); close() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); els[(i + 1) % els.length]?.focus() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); els[(i - 1 + els.length) % els.length]?.focus() }
    else if (e.key === 'Home') { e.preventDefault(); els[0]?.focus() }
    else if (e.key === 'End') { e.preventDefault(); els[els.length - 1]?.focus() }
    else if (e.key === 'Tab') setOpen(false)
  }

  const itemClass = (danger?: boolean) =>
    `w-full flex items-center gap-2 px-3 py-2 text-left text-xs rounded-lg outline-none transition-colors ${
      danger ? 'text-rose-300 hover:bg-rose-500/10 focus:bg-rose-500/10' : 'text-white/80 hover:bg-white/[0.06] focus:bg-white/[0.08]'
    }`

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true) } }}
        className="h-8 w-8 grid place-items-center rounded-lg text-white/55 hover:text-white hover:bg-white/[0.06] border border-transparent hover:border-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50 transition-colors"
      >
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKey}
          className="absolute right-0 top-9 z-30 min-w-[200px] rounded-xl border border-white/10 bg-[#111118] p-1 shadow-2xl shadow-black/60"
        >
          {items.map((it, idx) =>
            it.href ? (
              <a
                key={it.id}
                ref={(el) => { itemRefs.current[idx] = el }}
                role="menuitem"
                href={it.href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => close(false)}
                className={itemClass(it.danger)}
              >
                {it.icon}{it.label}
              </a>
            ) : (
              <button
                key={it.id}
                ref={(el) => { itemRefs.current[idx] = el }}
                type="button"
                role="menuitem"
                onClick={() => { close(); it.onSelect?.() }}
                className={itemClass(it.danger)}
              >
                {it.icon}{it.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  )
}

// ── Card shell ───────────────────────────────────────────────────────────────

export function CardShell({
  tone, icon, title, status, subtitle, menu, children, labelledBy,
}: {
  tone: 'local' | 'cloud'
  icon: React.ReactNode
  title: string
  status: ConnStatus
  subtitle: string
  menu: React.ReactNode
  children: React.ReactNode
  labelledBy: string
}) {
  const border = tone === 'local'
    ? 'border-cyan-400/30 bg-gradient-to-br from-cyan-500/[0.05] via-[#0b0d12] to-[#0a0a0f]'
    : 'border-indigo-400/25 bg-gradient-to-br from-blue-500/[0.05] via-[#0c0b14] to-violet-500/[0.04]'
  const tile = tone === 'local'
    ? 'bg-cyan-500/10 border-cyan-400/25 text-cyan-300'
    : 'bg-gradient-to-br from-blue-500/15 to-violet-500/15 border-violet-400/25 text-violet-200'
  return (
    <section aria-labelledby={labelledBy} className={`rounded-2xl border ${border} p-4 sm:p-5`}>
      <div className="flex items-start gap-3">
        <span className={`h-11 w-11 rounded-xl grid place-items-center border shrink-0 ${tile}`} aria-hidden>
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h3 id={labelledBy} className="text-[15px] font-bold text-white leading-tight">{title}</h3>
            <StatusPill status={status} />
          </div>
          <p className="text-xs text-white/50 mt-1">{subtitle}</p>
        </div>
        {menu}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  )
}

// ── Fields ───────────────────────────────────────────────────────────────────

export const FIELD_LABEL = 'block text-[11px] font-semibold text-white/55 mb-1.5'
const FIELD_BASE =
  'w-full h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-base sm:text-sm placeholder:text-white/30 outline-none focus:border-cyan-400/50 focus-visible:ring-2 focus-visible:ring-cyan-400/20 disabled:opacity-60 transition-colors'
export const INPUT = `${FIELD_BASE} text-white`
export const OUTLINE_BUTTON =
  'h-11 px-4 rounded-xl bg-black/40 border border-white/20 text-sm font-semibold text-white hover:bg-white/[0.06] hover:border-white/30 inline-flex items-center justify-center gap-2 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50 disabled:opacity-60 disabled:cursor-wait transition-colors'

export interface SelectOption {
  value: string
  label: string
  group?: string
  disabled?: boolean
}

export function ModelSelect({
  id, value, options, disabled, placeholder, onChange,
}: {
  id: string
  value: string
  options: SelectOption[]
  disabled: boolean
  placeholder: string
  onChange: (value: string) => void
}) {
  const groups: Array<{ name?: string; items: SelectOption[] }> = []
  for (const o of options) {
    const last = groups[groups.length - 1]
    if (last && last.name === o.group) last.items.push(o)
    else groups.push({ name: o.group, items: [o] })
  }
  const renderOption = (o: SelectOption) => (
    <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
  )
  // The placeholder ("Connect first…", "Select a model") reads dimmer than a chosen model.
  const tone = disabled ? 'text-white/35' : value ? 'text-white' : 'text-white/45'
  return (
    <div className="relative">
      <Box size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40 pointer-events-none" aria-hidden />
      <select
        id={id}
        value={disabled ? '' : value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={`${FIELD_BASE} ${tone} pl-9 pr-8 appearance-none disabled:cursor-not-allowed`}
      >
        <option value="" disabled>{placeholder}</option>
        {groups.map((g, i) =>
          g.name ? <optgroup key={`${g.name}-${i}`} label={g.name}>{g.items.map(renderOption)}</optgroup> : g.items.map(renderOption),
        )}
      </select>
      <svg className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-white/40" width="12" height="12" viewBox="0 0 12 12" aria-hidden>
        <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
}

export function FetchButton({ disabled, busy, onClick }: { disabled: boolean; busy: boolean; onClick: () => void }) {
  const enabled = !disabled && !busy
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={[
        'h-11 w-full sm:w-auto px-4 rounded-xl text-sm font-semibold inline-flex items-center justify-center gap-2 whitespace-nowrap transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60',
        enabled || busy
          ? 'bg-gradient-to-r from-cyan-500 to-violet-500 text-white shadow-lg shadow-violet-500/15 hover:brightness-110'
          : 'bg-white/[0.04] border border-white/10 text-white/35 opacity-70 cursor-not-allowed',
        busy ? 'cursor-wait' : '',
      ].join(' ')}
    >
      <RefreshCw size={15} className={busy ? 'animate-spin' : ''} aria-hidden />
      {busy ? 'Fetching…' : 'Fetch Models'}
    </button>
  )
}

// ── Inline messages ──────────────────────────────────────────────────────────

export function InfoLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 flex items-start gap-2 text-xs text-white/45">
      <Info size={14} className="shrink-0 mt-px text-white/40" aria-hidden />
      <span>{children}</span>
    </p>
  )
}

export function ErrorLine({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div role="alert" className="mt-3 flex flex-wrap items-start gap-2 rounded-xl border border-rose-500/25 bg-rose-500/[0.07] px-3 py-2 text-xs text-rose-200">
      <AlertCircle size={14} className="shrink-0 mt-px text-rose-300" aria-hidden />
      <span className="flex-1 min-w-[12rem]">{children}</span>
      {action}
    </div>
  )
}

export function WarnLine({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div role="alert" className="mt-3 flex flex-wrap items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2 text-xs text-amber-200">
      <AlertCircle size={14} className="shrink-0 mt-px text-amber-300" aria-hidden />
      <span className="flex-1 min-w-[12rem]">{children}</span>
      {action}
    </div>
  )
}
