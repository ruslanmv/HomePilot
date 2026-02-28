/**
 * useMeetingTts — Auto-speak persona messages in Teams meetings.
 *
 * Watches the meeting transcript for new assistant messages and speaks
 * them using the per-persona voice map (from usePersonaVoices).
 *
 * Additive hook — does not modify any existing meeting logic.
 *
 * Features:
 *   - One-at-a-time playback (SpeechSynthesis serialises automatically)
 *   - Strips <think>...</think> blocks and markdown noise before speaking
 *   - Respects the meetingTtsEnabled toggle
 *   - Tracks which messages have already been spoken (by id)
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import type { MeetingMessage } from './types'
import type { PersonaVoiceConfig } from './usePersonaVoices'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_TTS_KEY = 'homepilot_teams_tts_enabled'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Strip <think> blocks, markdown fences, and leading [sender]: prefixes. */
function cleanForSpeech(text: string): string {
  return text
    .replace(/<think>[\s\S]*?<\/think>/g, '')   // remove think blocks
    .replace(/```[\s\S]*?```/g, '')              // remove code fences
    .replace(/^\[.*?\]:\s*/gm, '')               // remove [SenderName]: prefix
    .replace(/[*_~`#>]/g, '')                    // strip markdown chars
    .replace(/\n{2,}/g, '\n')                    // collapse blank lines
    .trim()
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useMeetingTts(
  messages: MeetingMessage[],
  getPersonaVoice: (personaId: string) => PersonaVoiceConfig | undefined,
) {
  // ── Toggle state (persisted) ──
  const [enabled, setEnabled] = useState<boolean>(() => {
    return localStorage.getItem(LS_TTS_KEY) !== 'false'
  })

  useEffect(() => {
    localStorage.setItem(LS_TTS_KEY, String(enabled))
  }, [enabled])

  // ── Track which message IDs have been spoken ──
  // Seed with ALL existing message IDs on first render so we never replay
  // the full history when re-opening an old room.
  const spokenRef = useRef<Set<string>>(new Set(messages.map((m) => m.id)))
  const initialisedRef = useRef(false)

  // ── Speaking state for UI indicator ──
  const [speakingPersonaId, setSpeakingPersonaId] = useState<string | null>(null)

  // ── Speak queue: process ONLY genuinely new assistant messages ──
  useEffect(() => {
    // Skip the very first render — all messages at mount are historical.
    if (!initialisedRef.current) {
      // Mark every current message as already spoken
      for (const m of messages) spokenRef.current.add(m.id)
      initialisedRef.current = true
      return
    }

    if (!enabled) return
    if (!window.SpeechService?.speakWithConfig) return

    const unspoken = messages.filter(
      (m) => m.role === 'assistant' && !spokenRef.current.has(m.id),
    )

    if (unspoken.length === 0) return

    // Speak each new message sequentially (async IIFE)
    let cancelled = false
    ;(async () => {
      for (const msg of unspoken) {
        if (cancelled) break
        spokenRef.current.add(msg.id)

        const text = cleanForSpeech(msg.content)
        if (!text) continue

        const cfg = getPersonaVoice(msg.sender_id)

        setSpeakingPersonaId(msg.sender_id)
        await window.SpeechService!.speakWithConfig!(text, cfg || {}, {})
        setSpeakingPersonaId(null)
      }
    })()

    return () => { cancelled = true }
  }, [messages, enabled, getPersonaVoice])

  // ── Stop speaking ──
  const stop = useCallback(() => {
    window.SpeechService?.stopSpeaking?.()
    setSpeakingPersonaId(null)
  }, [])

  return {
    meetingTtsEnabled: enabled,
    setMeetingTtsEnabled: setEnabled,
    speakingPersonaId,
    stopSpeaking: stop,
  }
}
