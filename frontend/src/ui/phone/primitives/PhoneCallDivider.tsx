/**
 * PhoneCallDivider — neutral timeline separator for a phone call
 * inside a Grok-style chat / voice history.
 *
 * Design rules (from the product spec — docs/COMMUNICATION.md and
 * the design memo in the April 2026 session):
 *
 *   - A phone call is a **system event**, not a message. It belongs
 *     to neither side, so no bubble, no left/right alignment, no
 *     avatar, no CTA.
 *   - Rendered as a thin, centered, muted rule:
 *
 *       ──────── 📞 Phone call · 24s · 5:55 PM ────────
 *
 *   - Typography: 12 px, 40 % white — smaller and quieter than the
 *     17 px message font, so the eye skips it naturally when
 *     scanning a transcript.
 *   - Horizontal rules: 1 px, 8 % white — barely there, not a
 *     divider that competes with real content.
 *   - Vertical rhythm: ≈ 12 px top + 12 px bottom breathing room.
 *   - ``role="separator"`` so screen readers announce the event as
 *     a neutral divider rather than an unlabelled message.
 *
 * Consumers: ``VoiceModeGrok`` renders this in place of an empty
 * assistant bubble when a message carries a ``callMemory`` payload.
 * Chat mode has its own richer ``PostCallCard``; this primitive is
 * Voice-mode only by design.
 */
import React from 'react'
import { Phone } from 'lucide-react'

export interface PhoneCallDividerProps {
  /** Duration of the live phase, in seconds. Formatted as ``24s`` /
   *  ``3m`` / ``3m 12s``. */
  durationSec: number
  /** Epoch-ms timestamp of call-end. When present, rendered after
   *  the duration as a locale time (e.g. ``5:55 PM``). */
  endedAt?: number
  /** Optional className escape hatch so a caller can tweak spacing
   *  without re-authoring the primitive. Not expected to be used
   *  often; exists so consumers don't fork the component. */
  className?: string
}

function formatDuration(s: number): string {
  const clamped = Math.max(0, Math.floor(s))
  if (clamped < 60) return `${clamped}s`
  const m = Math.floor(clamped / 60)
  const rest = clamped % 60
  return rest === 0 ? `${m}m` : `${m}m ${rest}s`
}

function formatTime(ms: number): string {
  try {
    return new Date(ms).toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

const PhoneCallDivider: React.FC<PhoneCallDividerProps> = ({
  durationSec,
  endedAt,
  className,
}) => {
  const timeLabel = endedAt ? formatTime(endedAt) : ''
  const label = timeLabel
    ? `Phone call · ${formatDuration(durationSec)} · ${timeLabel}`
    : `Phone call · ${formatDuration(durationSec)}`
  return (
    <div
      role="separator"
      aria-label={label}
      className={[
        'flex items-center gap-3 py-3 my-1 text-white/40',
        'text-[12px] tracking-wide select-none',
        className ?? '',
      ].join(' ')}
    >
      <div className="flex-1 h-px bg-white/10" />
      <div className="flex items-center gap-1.5 whitespace-nowrap">
        <Phone size={11} className="opacity-70" aria-hidden="true" />
        <span>{label}</span>
      </div>
      <div className="flex-1 h-px bg-white/10" />
    </div>
  )
}

export default PhoneCallDivider
