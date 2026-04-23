/**
 * LiveChatPolish — purely presentational helpers for the Persona Live chat.
 *
 * Additive module: exports two small components (``AnimatedBubble`` +
 * ``TypewriterText``) plus a typing-indicator. The existing
 * ``ConversationOverlay`` in ``RuntimeShell`` can opt into these without
 * rewriting its message-store logic. Nothing here depends on the app's
 * API layer; these are framework-agnostic UI primitives.
 *
 * Animations use Tailwind's already-configured keyframes:
 *   - ``animate-fadeIn``    (160ms, opacity + 2px rise)
 *   - ``animate-msg-slide-in`` (320ms, cubic-bezier)
 * so we don't need a new animation dependency (framer-motion etc.).
 */
import React, { useEffect, useRef, useState } from 'react'

// ── TypewriterText ────────────────────────────────────────────────────────
// Reveals text one word at a time. Defaults tuned to feel "alive" without
// making the user wait on long replies:
//   - 14ms/token for short replies
//   - caps the total reveal at ~1.4s even for long replies (auto-skips
//     speed the remainder if the text is > 100 tokens)
// Props
//   text       — the final string to reveal. Changing text restarts.
//   speedMs    — baseline ms between tokens. Default 18.
//   instant    — render the final text immediately (useful for history).
//   className  — passthrough for styling.

export function TypewriterText({
  text,
  speedMs = 18,
  instant = false,
  className = '',
}: {
  text: string
  speedMs?: number
  instant?: boolean
  className?: string
}) {
  const [rendered, setRendered] = useState<string>(instant ? text : '')
  const tokensRef = useRef<string[]>([])
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (instant) {
      setRendered(text)
      return
    }
    // Split on whitespace but keep separators so rebuilt text matches the
    // source exactly (important for markdown / punctuation).
    const split = text.split(/(\s+)/)
    tokensRef.current = split
    setRendered('')

    let idx = 0
    // Cap total reveal at ~1.4s: if many tokens, step multiple per tick.
    const stride = Math.max(1, Math.ceil(split.length / 80))

    const step = () => {
      idx = Math.min(split.length, idx + stride)
      setRendered(tokensRef.current.slice(0, idx).join(''))
      if (idx < split.length) {
        timerRef.current = window.setTimeout(step, speedMs)
      }
    }
    timerRef.current = window.setTimeout(step, speedMs)
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current)
    }
  }, [text, speedMs, instant])

  return <span className={className}>{rendered}</span>
}

// ── TypingDots ────────────────────────────────────────────────────────────
// Three-dot bouncing indicator used while the AI reply is in flight.
// Reuses Tailwind's built-in ``animate-bounce`` with staggered delays so
// we inherit the same mechanism the main chat's AssistantSkeleton uses.

export function TypingDots({ className = '' }: { className?: string }) {
  return (
    <span className={['inline-flex items-end gap-1 h-4', className].join(' ')} aria-label="typing">
      <span
        className="w-1.5 h-1.5 rounded-full bg-white/70 animate-bounce"
        style={{ animationDelay: '0ms', animationDuration: '1.2s' }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-white/70 animate-bounce"
        style={{ animationDelay: '150ms', animationDuration: '1.2s' }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-white/70 animate-bounce"
        style={{ animationDelay: '300ms', animationDuration: '1.2s' }}
      />
    </span>
  )
}

// ── AnimatedBubble ────────────────────────────────────────────────────────
// Wrapper around a chat bubble that fades + slides in on mount. User
// bubbles get a purple accent; assistant bubbles get the charcoal glass
// look to match the screenshot.

export type BubbleRole = 'user' | 'assistant'

export function AnimatedBubble({
  role,
  children,
  status = 'done',
  className = '',
}: {
  role: BubbleRole
  children: React.ReactNode
  status?: 'sending' | 'streaming' | 'done' | 'error'
  className?: string
}) {
  const isUser = role === 'user'
  const errorRing = status === 'error' ? ' ring-1 ring-red-400/70' : ''
  const base = isUser
    ? 'bg-[#6b5bff]/50 text-white'
    : 'bg-black/55 text-white/95 backdrop-blur-md'
  const align = isUser ? 'justify-end' : 'justify-start'
  return (
    <div className={['flex', align].join(' ')}>
      <div
        className={[
          'max-w-[85%] rounded-2xl border border-white/15 px-3.5 py-2.5',
          'text-sm leading-relaxed shadow-[0_8px_20px_rgba(0,0,0,0.22)]',
          'animate-msg-slide-in',
          base,
          errorRing,
          className,
        ].join(' ')}
      >
        {children}
      </div>
    </div>
  )
}
