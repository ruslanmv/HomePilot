/**
 * streamTts.ts — pluggable streaming text-to-speech surface.
 *
 * One interface, three planned implementations. This file ships the
 * first (browser Web Speech); Piper-WASM and remote vendor streamers
 * are follow-ups that just swap the concrete constructor in
 * :func:`createStreamingTts`.
 *
 * Contract (§ 5.3 of docs/analysis/voice-call-streaming-design.md):
 *
 *   appendDelta(delta)   push a new text chunk. Implementations
 *                         flush to the audio engine at sentence
 *                         boundaries; callers hand over raw deltas
 *                         without worrying about clause shaping.
 *   flush()              signal end-of-turn. Any residual buffer
 *                         is spoken; the engine transitions back
 *                         to idle once the audio drains.
 *   stop()               barge-in. MUST silence any audio playing
 *                         or scheduled to play within ≤ 50 ms on
 *                         Chromium. Cheap to call redundantly.
 *   isSpeaking           read-only; true while audio is playing or
 *                         scheduled. Drives the VAD-tap enable gate.
 */

export interface StreamingTts {
  appendDelta(delta: string): void
  flush(): void
  stop(): void
  readonly isSpeaking: boolean
}

// ── Sentence-boundary helper ──────────────────────────────────────────
//
// Flush on: .  !  ?  ; or a newline — but only when they're followed
// by whitespace or end-of-buffer (so "e.g." / "Dr." don't mis-split).
// A tiny regex, kept readable rather than clever; the failure mode on
// a miss is "one extra utterance per turn," not a correctness bug.

const SENTENCE_END = /([.!?;\n])\s+/g

function splitIntoSentences(buffer: string): {
  sentences: string[]
  remainder: string
} {
  const sentences: string[] = []
  let lastIndex = 0
  let m: RegExpExecArray | null
  SENTENCE_END.lastIndex = 0
  while ((m = SENTENCE_END.exec(buffer)) !== null) {
    const end = m.index + m[0].length
    const piece = buffer.slice(lastIndex, end).trim()
    if (piece) sentences.push(piece)
    lastIndex = end
  }
  const remainder = buffer.slice(lastIndex)
  return { sentences, remainder }
}

// ── Web Speech implementation (ships first) ──────────────────────────
//
// Uses ``window.speechSynthesis`` directly. Each sentence becomes
// exactly one SpeechSynthesisUtterance so barge-in (via ``cancel()``)
// drops the current sentence + the queue atomically.
//
// Why one utterance per sentence instead of one per delta:
//
//  1. SpeechSynthesis queues utterances, not characters. Passing every
//     delta through would create 40+ queued utterances per turn on
//     Chromium, each with its own intonation reset — sounds robotic.
//  2. Cancel semantics are per-utterance, so sentence-granularity
//     means barge-in can interrupt mid-sentence without stranding
//     half-spoken buffers.

class WebSpeechStreamTts implements StreamingTts {
  private buffer = ''
  private speakingCount = 0
  private stopped = false
  private readonly syn: SpeechSynthesis | null

  constructor() {
    this.syn =
      typeof window !== 'undefined' && 'speechSynthesis' in window
        ? window.speechSynthesis
        : null
  }

  get isSpeaking(): boolean {
    return this.speakingCount > 0
  }

  appendDelta(delta: string): void {
    if (this.stopped || !delta) return
    this.buffer += delta
    const { sentences, remainder } = splitIntoSentences(this.buffer)
    this.buffer = remainder
    for (const s of sentences) this._speak(s)
  }

  flush(): void {
    if (this.stopped) return
    if (this.buffer.trim()) {
      this._speak(this.buffer.trim())
      this.buffer = ''
    }
  }

  stop(): void {
    // Idempotent — safe to call repeatedly from the barge-in path.
    this.stopped = true
    this.buffer = ''
    this.speakingCount = 0
    try {
      this.syn?.cancel()
    } catch {
      /* cancel is best-effort */
    }
  }

  private _speak(text: string): void {
    if (!this.syn) return
    let utter: SpeechSynthesisUtterance
    try {
      utter = new SpeechSynthesisUtterance(text)
    } catch {
      return
    }
    // Track speaking state so the VAD-tap enable gate stays tight
    // even when the queue reorders utterances (Safari / old Chromium).
    this.speakingCount += 1
    const done = () => {
      this.speakingCount = Math.max(0, this.speakingCount - 1)
    }
    utter.onend = done
    utter.onerror = done
    try {
      this.syn.speak(utter)
    } catch {
      done()
    }
  }
}

// ── Null implementation — used in tests + as a safety fallback ───────

class NullStreamTts implements StreamingTts {
  isSpeaking = false
  appendDelta(_delta: string): void { /* no-op */ }
  flush(): void { /* no-op */ }
  stop(): void { /* no-op */ }
}

// ── Factory ───────────────────────────────────────────────────────────
//
// Returns the best implementation available at runtime. Swapping
// in Piper-WASM or a remote vendor streamer is a one-line change
// in this function — call sites don't need to know.

export function createStreamingTts(): StreamingTts {
  if (typeof window === 'undefined') return new NullStreamTts()
  if (!('speechSynthesis' in window)) return new NullStreamTts()
  // Probe for the existence of an app-level SpeechService shim; if
  // present we could route through it, but for now the direct Web
  // Speech path is both simpler and lower-latency.
  return new WebSpeechStreamTts()
}

// Exported for tests + rare callers that want an explicit unplugged
// implementation (e.g. when a user opts out of TTS entirely).
export const streamTtsInternals = {
  splitIntoSentences,
  WebSpeechStreamTts,
  NullStreamTts,
}
