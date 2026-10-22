/**
 * Two pieces of the chat composer and its replies, kept out of App.tsx so they can be tested
 * on their own:
 *
 * - Long pastes become chips above the field, as ChatGPT and Claude show them, instead of a
 *   wall of text that stretches the composer over the conversation. The paste is sent with
 *   the message; the chip can be opened to read it, or removed.
 * - While the server summarizes a long conversation to fit the model's context, the reply
 *   shows that — three lines condensing into one — instead of a plain "Thinking".
 */
import React from 'react'
import { X } from 'lucide-react'

import { StatusText } from '../motion'

/** A paste the composer keeps as a chip rather than as text in the field: long enough that it
 *  would push the field past a few lines (1,200 characters, or 15 lines). */
export function isLongPaste(text: string): boolean {
  return text.length >= 1200 || text.split('\n').length >= 15
}

/** The message as sent: what was typed, then each kept paste, separated by a blank line. */
export function withPastes(typed: string, pastes: string[]): string {
  return [typed.trim(), ...pastes].filter(Boolean).join('\n\n')
}

export function PastedChips({
  pastes, open, onOpen, onRemove,
}: { pastes: string[]; open: number | null; onOpen: (i: number | null) => void; onRemove: (i: number) => void }) {
  if (!pastes.length) return null
  return (
    <div className="px-4 pt-3" data-testid="composer-pastes">
      <div className="flex flex-wrap gap-2">
        {pastes.map((p, i) => {
          const lines = p.split('\n').length
          return (
            <div key={i} className="relative">
              <button
                type="button"
                onClick={() => onOpen(open === i ? null : i)}
                aria-expanded={open === i}
                aria-label={`Pasted text, ${lines} lines. ${open === i ? 'Hide' : 'Show'} it`}
                className={[
                  'block w-48 rounded-xl border px-2.5 py-2 text-left transition-colors',
                  open === i ? 'border-violet-400/50 bg-violet-500/10' : 'border-white/10 bg-white/[0.04] hover:border-white/20',
                ].join(' ')}
              >
                {/* Three lines at most: an explicit clamp (a `block` class would override
                    Tailwind's line-clamp display and show the whole excerpt). */}
                <span
                  className="whitespace-pre-wrap break-words text-[11px] leading-snug text-white/60"
                  style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                  data-testid="composer-paste-excerpt"
                >
                  {p.slice(0, 280)}
                </span>
                <span className="mt-1.5 inline-flex rounded-md bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white/55">
                  Pasted · {lines.toLocaleString()} line{lines === 1 ? '' : 's'}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onRemove(i)}
                className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full border border-white/15 bg-[#1b1b1b] text-white/60 hover:text-white"
                aria-label="Remove pasted text"
              >
                <X size={11} />
              </button>
            </div>
          )
        })}
      </div>
      {open !== null && pastes[open] ? (
        <pre
          className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-black/30 p-3 text-[12px] leading-relaxed text-white/75"
          data-testid="composer-paste-preview"
        >
          {pastes[open]}
        </pre>
      ) : null}
    </div>
  )
}

/** While the server summarizes the earlier conversation (a long chat outgrew the model's
 *  context): three lines that condense into one, beside what is happening — the way Claude
 *  Code shows "Compacting conversation". Ends as soon as the answer starts. */
export function CompactingIndicator({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3" role="status" aria-live="polite" data-testid="compacting">
      <span className="hp-compact-lines" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <StatusText text={text} className="text-sm" />
    </div>
  )
}
