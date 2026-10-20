/**
 * The header and footer every HomePilot dialog shares, for use with `ModalSheet` (which owns
 * focus, Escape, the backdrop and the phone's Back gesture). Same shape as the Meetings dialogs:
 * a violet icon tile, the title and a short line under it, extra controls, and the close button.
 */
import React from 'react'
import { X, type LucideIcon } from 'lucide-react'
import { IconButton } from './Button'
import { IconTile } from './Surface'

type IconType = LucideIcon

export function SheetHeader({ id, icon, title, subtitle, actions, onClose, closeLabel = 'Close' }: {
  /** The title's id — pass the same value to ModalSheet's `labelledBy`. */
  id: string
  icon?: IconType
  title: React.ReactNode
  subtitle?: React.ReactNode
  actions?: React.ReactNode
  onClose: () => void
  closeLabel?: string
}) {
  return (
    <div className="flex items-start gap-4 border-b border-white/[0.06] px-5 py-5 sm:px-6">
      {icon ? <IconTile icon={icon} size="lg" /> : null}
      <div className="min-w-0 flex-1">
        <h2 id={id} className="text-lg font-semibold leading-tight text-white sm:text-xl">{title}</h2>
        {subtitle ? <p className="mt-1 text-sm text-white/55">{subtitle}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {actions}
        <IconButton label={closeLabel} icon={X} onClick={onClose} />
      </div>
    </div>
  )
}

export function SheetFooter({ children, start }: { children: React.ReactNode; start?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-white/[0.06] px-5 py-3 sm:px-6">
      {start ? <div className="min-w-0 flex-1">{start}</div> : <div className="flex-1" />}
      <div className="flex items-center gap-2">{children}</div>
    </div>
  )
}
