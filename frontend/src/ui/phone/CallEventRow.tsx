/**
 * CallEventRow — enterprise-grade inline render of a phone call in
 * the chat thread. Replaces the heavy PostCallCard card on desktop.
 *
 * Industry pattern (Slack Huddle / MS Teams "Meeting ended" /
 * Google Chat video event): a call is a SYSTEM EVENT in the
 * timeline, not a content block. We render it as:
 *
 *   State 1 — Default (collapsed):
 *
 *     ────────── 📞 Call · 26s · 22:54 ──────────
 *
 *     Thin centered divider, 12 px muted text, no box, no colored
 *     button. The whole label is clickable to expand.
 *
 *   State 2 — Hover (desktop):
 *
 *     ── 📞 Call · 26s · 22:54 ── Transcript · ↻ Resume ──
 *
 *     Action links fade in on hover (opacity 0 → 100). Text-weight,
 *     not pill buttons. Dot-separated, reads as one phrase.
 *
 *   State 3 — Expanded (on click):
 *
 *     ── 📞 Call · 26s · 22:54 ── Collapse · ↻ Resume ──
 *         You                are you very sexy right
 *         Secretary Sexy     That's a rather direct question…
 *
 *     Transcript prints inline unframed, indented, with a muted
 *     speaker label column. No background, no border, no rounded
 *     corners — just indented text that reads as part of the flow.
 *
 * Keeps PhoneCallDivider as the Voice-mode renderer (quieter, no
 * actions); CallEventRow is the chat-mode companion that adds the
 * reveal-on-demand affordances. Both components share the visual
 * language so the product reads consistently across surfaces.
 */
import React, { useState } from 'react'
import { Phone, RotateCcw } from 'lucide-react'

export interface CallEventTranscriptLine {
  who: 'user' | 'assistant'
  text: string
}

export interface CallEventRowProps {
  /** Live-phase duration in seconds. */
  durationSec: number
  /** Epoch-ms when the call ended. When present, rendered as a
   *  locale time (``22:54``); when absent, only the duration is shown. */
  endedAt?: number
  /** Display name of the persona, used as the left-column label for
   *  assistant lines in the expanded transcript. */
  personaName?: string
  /** Optional transcript. Absent / empty → hover actions and
   *  expansion affordance are hidden. */
  transcript?: CallEventTranscriptLine[]
  /** Resume handler. Absent → the "Resume" hover action is hidden. */
  onResume?: () => void
  /** Start expanded. Used post-call when the parent wants the
   *  transcript visible immediately; defaults to collapsed for
   *  reloaded history. */
  defaultExpanded?: boolean
  /** Escape hatch for consumers that want to tweak outer spacing
   *  without forking the component. */
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

/** Strip markdown image syntax from a transcript line so the raw
 *  URL doesn't render as text. Mirrors the sanitizer applied to
 *  TTS in App.tsx (stripMarkdownForSpeech). */
function stripTranscriptMarkup(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '')  // images
    .replace(/\s+/g, ' ')
    .trim()
}

const CallEventRow: React.FC<CallEventRowProps> = ({
  durationSec,
  endedAt,
  personaName,
  transcript,
  onResume,
  defaultExpanded = false,
  className,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const hasTranscript = !!(transcript && transcript.length > 0)
  const canResume = !!onResume
  const hasActions = hasTranscript || canResume

  const timeLabel = endedAt ? formatTime(endedAt) : ''
  const durLabel = formatDuration(durationSec)
  const summary = timeLabel ? `Call · ${durLabel} · ${timeLabel}` : `Call · ${durLabel}`
  const labelBtnLabel = expanded ? 'Collapse call row' : 'Expand call row'
  const rowClickable = hasTranscript

  return (
    <div
      role="region"
      aria-label={summary}
      className={['group my-2', className ?? ''].join(' ')}
    >
      {/* Divider rule + centered label + hover action cluster */}
      <div className="flex items-center gap-3 text-white/40 text-[12px] tracking-wide select-none">
        <div className="flex-1 h-px bg-white/10" />

        <button
          type="button"
          onClick={() => { if (rowClickable) setExpanded((v) => !v) }}
          disabled={!rowClickable}
          aria-label={labelBtnLabel}
          className={[
            'flex items-center gap-1.5 whitespace-nowrap transition-colors',
            rowClickable
              ? 'cursor-pointer hover:text-white/70'
              : 'cursor-default',
            'bg-transparent border-0 p-0 m-0 font-inherit',
          ].join(' ')}
        >
          <Phone size={11} aria-hidden="true" className="opacity-70" />
          <span>{summary}</span>
        </button>

        {hasActions && (
          <div
            className={[
              'flex items-center gap-2 text-[11px] text-white/45 whitespace-nowrap',
              // Hidden at rest, reveals on hover of the region.
              // Always visible when the row is expanded so the
              // Collapse link is reachable without re-hovering.
              expanded ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
              'transition-opacity duration-150',
            ].join(' ')}
          >
            {hasTranscript && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v) }}
                className="bg-transparent border-0 p-0 m-0 cursor-pointer hover:text-white/85 transition-colors"
              >
                {expanded ? 'Collapse' : 'Transcript'}
              </button>
            )}
            {hasTranscript && canResume && (
              <span className="text-white/20" aria-hidden="true">·</span>
            )}
            {canResume && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onResume!() }}
                className="inline-flex items-center gap-1 bg-transparent border-0 p-0 m-0 cursor-pointer hover:text-white/85 transition-colors"
                aria-label="Resume call"
              >
                <RotateCcw size={10} aria-hidden="true" className="opacity-80" />
                <span>Resume</span>
              </button>
            )}
          </div>
        )}

        <div className="flex-1 h-px bg-white/10" />
      </div>

      {/* Expanded transcript — inline, unframed */}
      {expanded && hasTranscript && (
        <div className="mt-3 mb-1 space-y-1.5">
          {transcript!.map((line, i) => {
            const label = line.who === 'user' ? 'You' : (personaName || 'Assistant')
            return (
              <div key={i} className="flex gap-4 text-[13.5px] leading-relaxed">
                <div className="w-28 flex-shrink-0 text-white/35 text-[11px] uppercase tracking-wider pt-0.5">
                  {label}
                </div>
                <div className="flex-1 text-white/75">
                  {stripTranscriptMarkup(line.text)}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default CallEventRow
