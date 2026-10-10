/**
 * A quiet, dismissible notice from the Model Advisor: a clearly better model fits this
 * computer, or the suggestions changed (new FitLab definitions, or a HomePilot update).
 *
 * One notice at a time, never modal, never repeated once dismissed: "Not now" snoozes
 * that notice for 7 days, "Turn off" disables advisor notifications on this device
 * (Settings → Models → Model suggestions turns them back on).
 */
import React from 'react'
import { Sparkles, X } from 'lucide-react'
import { KIND_LABEL, type AdvisorNotice } from '../modelAdvisor'

export function AdvisorUpdateNotice({
  notice,
  onView,
  onDismiss,
  onTurnOff,
}: {
  notice: AdvisorNotice
  onView: () => void
  onDismiss: () => void
  onTurnOff: () => void
}) {
  const title = notice.type === 'upgrade'
    ? `Better ${KIND_LABEL[notice.kind].toLowerCase()} model for this computer`
    : notice.firstTime ? 'New: model suggestions for your GPU' : 'Model suggestions updated'
  const body = notice.type === 'upgrade'
    ? `${notice.better.name} ranks above ${notice.currentName} on this machine. ${notice.better.reasons[0] || ''}`
    : notice.firstTime
      ? 'See which chat, vision, image and video models fit this computer best.'
      : 'New FitLab definitions or a HomePilot update changed which models fit this computer best.'
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed left-4 right-4 top-16 z-[70] sm:left-auto sm:w-[22rem] rounded-2xl border border-violet-400/25 bg-[#14121c]/95 p-4 shadow-[0_18px_50px_rgba(0,0,0,0.55)] backdrop-blur"
      data-testid="advisor-notice"
    >
      <div className="flex items-start gap-3">
        <Sparkles size={16} className="mt-0.5 shrink-0 text-violet-300" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="mt-1 text-xs leading-snug text-white/65">{body}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={onView} className="h-8 rounded-lg bg-violet-500/80 px-3 text-xs font-semibold text-white hover:bg-violet-500">
              View
            </button>
            <button type="button" onClick={onDismiss} className="h-8 rounded-lg px-3 text-xs text-white/70 hover:bg-white/[0.07]">
              Not now
            </button>
            <button type="button" onClick={onTurnOff} className="ml-auto h-8 rounded-lg px-2 text-[11px] text-white/45 hover:text-white/75">
              Turn off notifications
            </button>
          </div>
        </div>
        <button type="button" onClick={onDismiss} aria-label="Close" className="-mr-1 -mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-white/45 hover:bg-white/[0.07] hover:text-white">
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

export default AdvisorUpdateNotice
