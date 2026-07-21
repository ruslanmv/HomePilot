/**
 * RemoteOfflineBanner (Batch 6) — honest offline state.
 *
 * When the user has PINNED a specific computer that is offline, this shows a
 * persistent banner ("Studio PC is offline — turn it on to continue") with
 * Troubleshoot / Notify actions. Combined with the send guard in App
 * (sendTextOrIntent), it guarantees no silent Web-CPU downgrade for a pinned
 * selection.
 *
 * ADDITIVE and self-contained: renders null unless a pinned computer is
 * offline, so mounting it changes nothing by default. It also briefly pulses
 * when a blocked send fires the `homepilot:remote-offline-nudge` event.
 */
import React, { useEffect, useState } from 'react'
import { AlertTriangle, Bell, BellRing, Wrench, X } from 'lucide-react'

import { useComputer } from './ComputerContext'
import { useSelectedOfflineNode } from './useRemoteChatTarget'

export function RemoteOfflineBanner(): JSX.Element | null {
  const offline = useSelectedOfflineNode()
  const { selectComputer } = useComputer()
  const [pulse, setPulse] = useState(false)
  const [notified, setNotified] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Reset transient UI when the offline node changes (e.g. it came back online).
  useEffect(() => {
    setDismissed(false)
    setNotified(false)
  }, [offline?.nodeId])

  // Flash when a send is blocked so the user connects the dots.
  useEffect(() => {
    const onNudge = () => {
      setDismissed(false)
      setPulse(true)
      window.setTimeout(() => setPulse(false), 1400)
    }
    window.addEventListener('homepilot:remote-offline-nudge', onNudge)
    return () => window.removeEventListener('homepilot:remote-offline-nudge', onNudge)
  }, [])

  if (!offline || dismissed) return null

  const openSettings = () =>
    window.dispatchEvent(new CustomEvent('homepilot:open-settings', { detail: { section: 'account' } }))

  return (
    <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[120] w-[min(560px,calc(100vw-2rem))]">
      <div
        className={[
          'rounded-2xl border px-4 py-3 flex items-start gap-3 shadow-2xl backdrop-blur',
          'bg-amber-500/[0.12] border-amber-400/30 text-amber-100',
          pulse ? 'ring-2 ring-amber-400/70 animate-pulse' : '',
        ].join(' ')}
        role="status"
      >
        <AlertTriangle size={18} className="text-amber-300 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{offline.nodeName} is offline</div>
          <div className="text-[12px] text-amber-100/70">
            This chat is set to run on {offline.nodeName}. Turn that computer on to continue —
            HomePilot won't silently run it here.
          </div>
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={openSettings}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 border border-white/15 inline-flex items-center gap-1"
            >
              <Wrench size={12} /> Troubleshoot
            </button>
            <button
              onClick={() => setNotified(true)}
              disabled={notified}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 border border-white/15 inline-flex items-center gap-1 disabled:opacity-70"
            >
              {notified ? <><BellRing size={12} /> We'll notify you</> : <><Bell size={12} /> Notify me when online</>}
            </button>
            <button
              onClick={() => selectComputer(null)}
              className="text-[11px] px-2.5 py-1 rounded-lg text-amber-100/70 hover:text-amber-100"
            >
              Use Automatic
            </button>
          </div>
        </div>
        <button onClick={() => setDismissed(true)} className="text-amber-100/50 hover:text-amber-100 shrink-0" aria-label="Dismiss">
          <X size={15} />
        </button>
      </div>
    </div>
  )
}
