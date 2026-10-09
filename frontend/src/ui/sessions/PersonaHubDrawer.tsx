/**
 * PersonaHubDrawer — the frame of a project's Conversation Hub.
 *
 * The project's identity (picture, name, details) is drawn by the content,
 * so the frame carries only a close button: the name is no longer shown twice.
 * Built on ModalSheet: full-screen on phones, a centred card above, Escape /
 * backdrop / the phone's Back gesture close it, focus is kept inside.
 */
import React from 'react'
import { X } from 'lucide-react'
import { ModalSheet } from '../components/ModalSheet'

type Props = {
  open: boolean
  /** The project's name — the dialog's accessible name. */
  title: string
  /** Kept for compatibility; the hub content shows the project's details. */
  subtitle?: string
  metaRight?: React.ReactNode
  onClose: () => void
  children: React.ReactNode
}

export default function PersonaHubDrawer({ open, title, metaRight, onClose, children }: Props) {
  if (!open) return null
  return (
    <ModalSheet
      label={`${title} — conversation hub`}
      onRequestClose={onClose}
      zIndex={60}
      className="hp-hub-sheet"
      header={
        <div className="flex items-center justify-end gap-2 px-3 pt-3 -mb-14 relative z-10 pointer-events-none">
          {metaRight ? <div className="pointer-events-auto">{metaRight}</div> : null}
          <button
            type="button"
            onClick={onClose}
            className="pointer-events-auto h-11 w-11 grid place-items-center rounded-full text-white/70 hover:text-white hover:bg-white/10"
            aria-label="Close"
            title="Close"
          >
            <X size={20} />
          </button>
        </div>
      }
    >
      <div className="px-4 sm:px-6 pt-4 pb-6">{children}</div>
    </ModalSheet>
  )
}
