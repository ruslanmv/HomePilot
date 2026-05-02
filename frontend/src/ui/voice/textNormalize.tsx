/**
 * textNormalize — shared text utilities for Voice mode.
 *
 * Two surfaces in voice rendering share the same source of truth for how
 * to strip / parse markdown-ish decorations that persona LLMs commonly
 * emit — single-asterisk roleplay actions ("*I smile*"), bold, italics,
 * strikethrough, inline code, headings, blockquotes, images, links.
 *
 * Motivation: without this step, the TTS engine literally reads the
 * asterisks out loud as "asterisk I smile asterisk" and the screen shows
 * raw ``*I smile*`` instead of rendering the action as emphasized text.
 *
 * Two exports:
 *
 *   normalizeForSpeech(text)
 *     Returns a plain-text string safe to hand to
 *     ``window.speechSynthesis`` / the TTS backend. Strips every markdown
 *     decoration but keeps the inner text. Drops image markdown entirely
 *     (the user sees the image, no need for TTS to say "alt text").
 *
 *   parseVoiceInline(line, onImageClick?)
 *     Returns a list of React nodes for the on-screen bubble. Renders
 *     images + links as real elements (reusing the existing pattern in
 *     VoiceModeGrok.parseInlineMarkdown) AND emphasis markers as italic
 *     / bold spans instead of literal asterisks. Safe to mix inside the
 *     existing line-by-line render loop.
 *
 * Both functions are pure, side-effect-free, and framework-agnostic
 * (the React node output uses ``React.createElement`` indirectly via
 * JSX; we import React only for typing).
 */
import React from 'react'

// ── Regex vocabulary (shared) ───────────────────────────────────────────
// Keep these non-greedy so nested/adjacent markers don't collide.

// ![alt](url) — image markdown
const RE_MD_IMAGE = /!\[[^\]]*\]\([^)]+\)/g

// [text](url) — link markdown
const RE_MD_LINK = /\[([^\]]+)\]\([^)]+\)/g

// ```code fence``` (multiline; non-greedy)
const RE_MD_FENCE = /```[\s\S]*?```/g

// `inline code`
const RE_MD_CODE = /`([^`]+)`/g

// ***bold italic*** — must match before **bold** and *italic*
const RE_MD_STRONG_EM = /\*\*\*([^*]+)\*\*\*/g

// **bold** or __bold__
const RE_MD_STRONG_STAR = /\*\*([^*]+)\*\*/g
const RE_MD_STRONG_UNDER = /__([^_]+)__/g

// *italic* — common for persona roleplay actions ("*I smile*")
// Negative look-around avoids eating list-item markers ("* item") at line start.
const RE_MD_EM_STAR = /(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])/g

// _italic_ — less common but persona LLMs do emit it
const RE_MD_EM_UNDER = /(?<![_\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![_\w])/g

// ~~strikethrough~~
const RE_MD_STRIKE = /~~([^~]+)~~/g

// Leading heading hashes: "## foo" → "foo" (strip up to 6 #, then the space)
const RE_MD_HEADING = /^\s*#{1,6}\s+/gm

// Leading blockquote arrows: "> quote" → "quote"
const RE_MD_QUOTE = /^\s*>\s?/gm


// ── TTS path ────────────────────────────────────────────────────────────

/** Collapse every markdown decoration into plain text for speech synthesis.
 *  Stable surface for ``App.tsx`` / ``CallOverlay`` / ``CreatorStudioEditor``
 *  — kept parameter-compatible with the older ``stripMarkdownForSpeech``. */
export function normalizeForSpeech(text: string): string {
  if (!text) return ''
  return text
    // Images: drop entirely — the user sees them, speech shouldn't describe them.
    .replace(RE_MD_IMAGE, '')
    // Links: keep the visible label, drop the URL.
    .replace(RE_MD_LINK, '$1')
    // Arrow glyphs that commonly sit between a tool-call and the removed
    // image — "outfit → " leftover → "outfit".
    .replace(/\s*→\s*(?=$|\n)/g, '')
    // Code: strip fences + inline backticks, keep inner text.
    .replace(RE_MD_FENCE, (m) => m.slice(3, -3).trim())
    .replace(RE_MD_CODE, '$1')
    // Emphasis: order matters. Strongest first so ``***x***`` doesn't
    // collapse to ``*x*`` halfway.
    .replace(RE_MD_STRONG_EM, '$1')
    .replace(RE_MD_STRONG_STAR, '$1')
    .replace(RE_MD_STRONG_UNDER, '$1')
    .replace(RE_MD_EM_STAR, '$1')
    .replace(RE_MD_EM_UNDER, '$1')
    .replace(RE_MD_STRIKE, '$1')
    // Block-level: headings, blockquotes.
    .replace(RE_MD_HEADING, '')
    .replace(RE_MD_QUOTE, '')
    // Tidy up the whitespace we left behind.
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}


// ── Display path ────────────────────────────────────────────────────────

/** Render a single line of text as React nodes, giving italic / bold /
 *  strike / inline-code their correct visual treatment and delegating
 *  image + link rendering to the caller's handler. Safe inside a
 *  typewriter reveal — pure function, no state. */
export function parseVoiceInline(
  line: string,
  onImageClick?: (src: string) => void,
  renderImageLink?: (raw: string, onImageClick?: (src: string) => void) => React.ReactNode,
): React.ReactNode[] {
  if (!line) return []
  const out: React.ReactNode[] = []

  // First pass: split on combined markdown regex and emit typed nodes.
  // The caller still owns image/link rendering (needs backend URL
  // resolution, auth tokens, etc.) so we delegate that via renderImageLink.
  // If renderImageLink isn't provided, we leave the raw markdown in place
  // and only strip the ``*`` / ``_`` / ``~~`` markers — still a big win.
  const combined = new RegExp(
    [
      '(!?\\[[^\\]]*\\]\\([^)]+\\))',          // 1) image or link
      '(\\*\\*\\*([^*]+)\\*\\*\\*)',            // 2) bold-italic ***x***
      '(\\*\\*([^*]+)\\*\\*)',                  // 3) bold **x**
      '(__([^_]+)__)',                          // 4) bold __x__
      '((?<![*\\w])\\*(?!\\s)([^*\\n]+?)(?<!\\s)\\*(?![*\\w]))', // 5) *italic*
      '((?<![_\\w])_(?!\\s)([^_\\n]+?)(?<!\\s)_(?![_\\w]))',      // 6) _italic_
      '(~~([^~]+)~~)',                          // 7) ~~strike~~
      '(`([^`]+)`)',                            // 8) `code`
    ].join('|'),
    'g',
  )

  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = combined.exec(line)) !== null) {
    if (match.index > lastIndex) out.push(line.slice(lastIndex, match.index))
    const raw = match[0]
    if (match[1]) {
      // Image or link — delegate if caller provided a renderer.
      out.push(renderImageLink ? renderImageLink(raw, onImageClick) : raw)
    } else if (match[2]) {
      out.push(
        <strong key={`bi-${key++}`}><em>{match[3]}</em></strong>,
      )
    } else if (match[4]) {
      out.push(<strong key={`b-${key++}`}>{match[5]}</strong>)
    } else if (match[6]) {
      out.push(<strong key={`bu-${key++}`}>{match[7]}</strong>)
    } else if (match[8]) {
      // *italic* — common roleplay action. Slightly subdued colour so
      // the speech bubble reads like narration rather than regular voice.
      out.push(
        <em key={`i-${key++}`} className="text-white/80 italic">{match[9]}</em>,
      )
    } else if (match[10]) {
      out.push(
        <em key={`iu-${key++}`} className="text-white/80 italic">{match[11]}</em>,
      )
    } else if (match[12]) {
      out.push(<s key={`s-${key++}`}>{match[13]}</s>)
    } else if (match[14]) {
      out.push(
        <code
          key={`c-${key++}`}
          className="px-1 py-0.5 rounded bg-white/10 text-white/90 font-mono text-[0.9em]"
        >
          {match[15]}
        </code>,
      )
    }
    lastIndex = match.index + raw.length
  }
  if (lastIndex < line.length) out.push(line.slice(lastIndex))
  return out
}
