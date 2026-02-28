/**
 * PersonaVoiceChip — Inline voice preview chip for persona cards.
 *
 * Shows the selected voice name (or "Default voice") with a one-click
 * preview button. Used in persona cards, Teams People panel, and
 * the wizard Review step.
 *
 * Additive — no existing logic is modified.
 */

import React, { useState, useCallback } from 'react'
import { Volume2 } from 'lucide-react'
import type { PersonaVoiceConfig } from '../../personaTypes'

export function PersonaVoiceChip({
  personaName,
  voice,
  size = 'md',
}: {
  personaName: string
  voice?: PersonaVoiceConfig
  size?: 'sm' | 'md'
}) {
  const [speaking, setSpeaking] = useState(false)

  const voiceLabel = voice?.voiceURI
    ? voice.name || voice.voiceURI
    : 'Default voice'

  const isSmall = size === 'sm'

  const handlePreview = useCallback(async () => {
    const svc = (window as any).SpeechService
    if (!svc?.speakWithConfig || speaking) return

    setSpeaking(true)
    const text = `Hi, I am ${personaName}. This is my voice.`
    await svc.speakWithConfig(
      text,
      {
        voiceURI: voice?.voiceURI,
        rate: voice?.rate ?? 1.0,
        pitch: voice?.pitch ?? 1.0,
        volume: voice?.volume ?? 1.0,
      },
      { onEnd: () => setSpeaking(false), onError: () => setSpeaking(false) },
    )
    setSpeaking(false)
  }, [personaName, voice, speaking])

  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-full border bg-white/[0.03] border-white/[0.08] ${
        isSmall ? 'px-2 py-0.5 text-[10px]' : 'px-3 py-1.5 text-xs'
      } text-white/50`}
    >
      <span className="truncate max-w-[140px]">{voiceLabel}</span>

      <button
        type="button"
        onClick={handlePreview}
        disabled={speaking}
        className={`p-0.5 rounded-full transition-colors ${
          speaking
            ? 'text-purple-300'
            : 'text-white/35 hover:text-purple-300'
        }`}
        title="Preview voice"
      >
        <Volume2 size={isSmall ? 10 : 13} className={speaking ? 'animate-pulse' : ''} />
      </button>
    </div>
  )
}
