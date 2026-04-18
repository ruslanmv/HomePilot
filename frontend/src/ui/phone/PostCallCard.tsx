/**
 * PostCallCard — inline "we just talked" record rendered directly
 * in the chat thread, NOT as a modal. Product direction from the
 * engineering handoff:
 *
 *   "You are building a conversational / companion experience,
 *    not a compliance tool. → Use inline card + expandable
 *    transcript."
 *
 * Three variants covering the full (variant × missed) matrix from
 * the handoff's § 3:
 *
 *   expand      — default. Duration + time + [Resume call] +
 *                  [View transcript ▾]. Tapping the latter expands
 *                  the transcript INLINE inside the same card (no
 *                  modal). Keeps the call record as an event in
 *                  the conversation the user can glance at later.
 *   highlights  — same shell, but the body is a short italic
 *                  "Vesper remembers…" summary + a [Full transcript]
 *                  link. For sessions where the call was long and
 *                  the full transcript is too long to inline.
 *   missed      — red tint, phone-slash icon, single [Call back]
 *                  CTA. Set via ``missed`` prop (orthogonal to
 *                  variant; a missed call is always rendered as the
 *                  missed variant, others ignored).
 *
 * This component replaces the prior enterprise-neutral
 * CallMemoryCard. The enterprise form (flat surface, \"Voice session
 * completed\" copy) is preserved as a setting-free default by
 * passing only durationSec + endedAt; richer props turn on the
 * conversational surface.
 */

import React, { useState } from 'react'
import {
  IconPhone,
  IconPhoneMissed,
  IconSparkle,
} from './icons'
import { CALL, POST_CALL } from './tokens'

// ── Props ────────────────────────────────────────────────────────

export type PostCallVariant = 'expand' | 'highlights'

export interface TranscriptLine {
  who: 'user' | 'assistant'
  text: string
}

export interface PostCallCardProps {
  /** Live-phase duration in seconds. Rendered as "12s" / "1m 4s" /
   *  "12 min" depending on magnitude. */
  durationSec: number
  /** Epoch-ms timestamp of when the call ended. Rendered as
   *  "8:14 PM" via toLocaleTimeString. */
  endedAt?: number
  /** The persona the user was talking to. Drives the body text
   *  ("Call with Vesper"). Default "Assistant". */
  personaName?: string
  /** Variant — see module docstring. */
  variant?: PostCallVariant
  /** Missed-call variant — tints red, shows phone-slash icon,
   *  swaps the CTAs. */
  missed?: boolean
  /** Optional transcript. When present AND variant='expand',
   *  enables the inline expand button. */
  transcript?: TranscriptLine[]
  /** Optional short summary for variant='highlights'
   *  (e.g. "You talked about Lisbon and made plans for Friday"). */
  summary?: string
  /** "Resume call" click — re-open the call overlay with
   *  skipDialing=true. */
  onResume?: () => void
  /** "Call back" click on the missed variant. Defaults to the same
   *  as onResume when omitted. */
  onCallBack?: () => void
  /** "Full transcript" click on the highlights variant — typically
   *  opens a separate route or sheet. Optional; button hides when
   *  handler isn't provided. */
  onOpenFullTranscript?: () => void
}

// ── Helpers ──────────────────────────────────────────────────────

function formatDuration(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  if (r === 0) return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`
  return `${m} min ${r}s`
}

function formatClock(endedAt: number): string {
  return new Date(endedAt).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

// ── Component ────────────────────────────────────────────────────

const PostCallCard: React.FC<PostCallCardProps> = ({
  durationSec,
  endedAt,
  personaName = 'Assistant',
  variant = 'expand',
  missed = false,
  transcript,
  summary,
  onResume,
  onCallBack,
  onOpenFullTranscript,
}) => {
  const [expanded, setExpanded] = useState(false)
  const clock = endedAt ? formatClock(endedAt) : ''
  const dur = formatDuration(durationSec)
  const accent = missed ? CALL.danger : CALL.rose
  const hasTranscript = !!(transcript && transcript.length > 0)

  // Top row — icon, title, sub.
  const subtitle = missed
    ? clock
      ? `${clock} · tap to call back`
      : 'tap to call back'
    : clock
      ? `${dur} · ${clock}`
      : dur

  const titleText = missed
    ? `Missed call · ${personaName}`
    : `Call with ${personaName}`

  return (
    <div
      role="note"
      aria-label={missed ? `Missed call from ${personaName}` : `Call with ${personaName}`}
      className="hp-fade-in"
      style={{
        width: POST_CALL.cardWidth,
        maxWidth: '100%',
        borderRadius: POST_CALL.cardRadius,
        overflow: 'hidden',
        background: missed
          ? `linear-gradient(180deg, color-mix(in oklch, ${accent} 12%, transparent) 0%, rgba(245,236,255,0.03) 100%)`
          : 'linear-gradient(180deg, rgba(245,236,255,0.06) 0%, rgba(245,236,255,0.03) 100%)',
        border: missed
          ? `0.5px solid color-mix(in oklch, ${accent} 35%, transparent)`
          : `0.5px solid ${CALL.line}`,
        fontFamily: CALL.font,
        color: CALL.ink,
      }}
    >
      {/* Header row — icon + title + time */}
      <div
        style={{
          padding: POST_CALL.rowPadding,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <div
          aria-hidden="true"
          style={{
            width: POST_CALL.avatarSize,
            height: POST_CALL.avatarSize,
            borderRadius: '50%',
            background: `color-mix(in oklch, ${accent} 20%, transparent)`,
            border: `0.5px solid color-mix(in oklch, ${accent} 40%, transparent)`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: accent,
            flexShrink: 0,
          }}
        >
          {missed ? (
            <IconPhoneMissed size={14} color={accent} />
          ) : (
            <IconPhone size={14} color={accent} />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: -0.1,
              color: missed ? accent : CALL.ink,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {titleText}
          </div>
          <div
            style={{
              fontSize: 11,
              color: CALL.dim,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {subtitle}
          </div>
        </div>
      </div>

      {/* Highlights body — italic summary line (only when variant is
          'highlights' and we're not in the missed state). */}
      {variant === 'highlights' && !missed && summary ? (
        <div
          style={{
            padding: '4px 14px 12px',
            fontFamily: CALL.display,
            fontSize: 15,
            lineHeight: 1.4,
            color: 'rgba(245,236,255,0.82)',
            fontStyle: 'italic',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              marginBottom: 4,
              fontFamily: CALL.font,
              fontStyle: 'normal',
              fontSize: 9,
              color: 'oklch(0.80 0.15 340)',
              letterSpacing: 1.4,
              textTransform: 'uppercase',
            }}
          >
            <IconSparkle size={9} color="oklch(0.80 0.15 340)" />
            {personaName} remembers
          </div>
          <span>&ldquo;{summary}&rdquo;</span>
        </div>
      ) : null}

      {/* Expanded transcript — inline, NOT a modal. Renders only for
          variant='expand' when the user has clicked the expand button
          and a transcript was provided. */}
      {variant === 'expand' && expanded && !missed && hasTranscript ? (
        <div
          style={{
            padding: '2px 14px 12px',
            borderTop: `0.5px solid ${CALL.line}`,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <div
            style={{
              fontSize: 9,
              letterSpacing: 1.4,
              textTransform: 'uppercase',
              color: 'rgba(245,236,255,0.4)',
              paddingTop: 10,
            }}
          >
            Transcript
          </div>
          {(transcript as TranscriptLine[]).map((line, i) => (
            <div key={i} style={{ fontSize: 12, lineHeight: 1.45 }}>
              <span
                style={{
                  color:
                    line.who === 'user'
                      ? 'oklch(0.80 0.15 50)'
                      : 'oklch(0.80 0.15 340)',
                  fontWeight: 600,
                  marginRight: 6,
                }}
              >
                {line.who === 'user' ? 'You' : personaName}
              </span>
              <span style={{ color: 'rgba(245,236,255,0.85)' }}>
                {line.text}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {/* CTA row */}
      <div
        style={{
          display: 'flex',
          gap: 6,
          padding: '8px 10px 10px',
          borderTop:
            variant === 'expand' && expanded && !missed && hasTranscript
              ? 'none'
              : `0.5px solid ${CALL.line}`,
        }}
      >
        <button
          type="button"
          onClick={missed ? (onCallBack ?? onResume) : onResume}
          disabled={!(missed ? (onCallBack ?? onResume) : onResume)}
          aria-label={missed ? 'Call back' : 'Resume call'}
          style={{
            flex: 1,
            height: POST_CALL.ctaHeight,
            borderRadius: POST_CALL.ctaRadius,
            cursor: 'pointer',
            background: accent,
            color: '#0c0810',
            border: 'none',
            fontFamily: CALL.font,
            fontSize: 12,
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
          }}
        >
          <IconPhone size={12} color="#0c0810" />
          {missed ? 'Call back' : 'Resume call'}
        </button>

        {/* Secondary CTA — only the non-missed variants have one */}
        {!missed && variant === 'highlights' && onOpenFullTranscript ? (
          <button
            type="button"
            onClick={onOpenFullTranscript}
            aria-label="Open full transcript"
            style={{
              flex: 1,
              height: POST_CALL.ctaHeight,
              borderRadius: POST_CALL.ctaRadius,
              cursor: 'pointer',
              background: 'rgba(245,236,255,0.06)',
              color: CALL.ink,
              border: `0.5px solid ${CALL.line}`,
              fontFamily: CALL.font,
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            Full transcript
          </button>
        ) : null}

        {!missed && variant === 'expand' && hasTranscript ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse transcript' : 'View transcript'}
            style={{
              flex: 1,
              height: POST_CALL.ctaHeight,
              borderRadius: POST_CALL.ctaRadius,
              cursor: 'pointer',
              background: 'rgba(245,236,255,0.06)',
              color: CALL.ink,
              border: `0.5px solid ${CALL.line}`,
              fontFamily: CALL.font,
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            {expanded ? 'Collapse ▴' : 'View transcript ▾'}
          </button>
        ) : null}
      </div>
    </div>
  )
}

export default PostCallCard

// Test hooks — exposed for unit tests without widening the public API.
export const postCallCardInternals = {
  formatDuration,
  formatClock,
}
