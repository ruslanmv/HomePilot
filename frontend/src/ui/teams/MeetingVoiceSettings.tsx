/**
 * MeetingVoiceSettings — Voice settings panel for Teams meetings.
 *
 * Additive slide-over drawer that shows:
 *   1. Meeting TTS toggle (enable/disable voice playback)
 *   2. Per-persona voice picker (different voice per persona)
 *   3. Rate/pitch/volume sliders per persona
 *
 * Designed to match the TeamsSettingsDrawer visual style.
 */

import React, { useCallback, useMemo, useState } from 'react'
import { X, Volume2, VolumeX, ChevronDown, ChevronRight } from 'lucide-react'
import type { PersonaSummary } from './types'
import type { PersonaVoiceConfig } from './usePersonaVoices'
import { PersonaVoicePicker } from './PersonaVoicePicker'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MeetingVoiceSettingsProps {
  open: boolean
  onClose: () => void
  participants: PersonaSummary[]
  backendUrl: string
  /** Current TTS enabled state */
  meetingTtsEnabled: boolean
  onToggleTts: (enabled: boolean) => void
  /** Per-persona voice access */
  getPersonaVoice: (personaId: string) => PersonaVoiceConfig | undefined
  setPersonaVoice: (personaId: string, cfg: PersonaVoiceConfig) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveAvatarUrl(p: PersonaSummary, backendUrl: string): string | null {
  const file = p.persona_appearance?.selected_thumb_filename || p.persona_appearance?.selected_filename
  if (!file) return null
  if (file.startsWith('http')) return file
  return `${backendUrl}/files/${file}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MeetingVoiceSettings({
  open,
  onClose,
  participants,
  backendUrl,
  meetingTtsEnabled,
  onToggleTts,
  getPersonaVoice,
  setPersonaVoice,
}: MeetingVoiceSettingsProps) {
  const [advancedOpen, setAdvancedOpen] = useState<Set<string>>(new Set())

  const toggleAdvanced = useCallback((personaId: string) => {
    setAdvancedOpen((prev) => {
      const next = new Set(prev)
      if (next.has(personaId)) next.delete(personaId)
      else next.add(personaId)
      return next
    })
  }, [])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />

      {/* Drawer */}
      <div className="relative w-80 max-w-[90vw] h-full bg-[#0a0a0a] border-l border-white/[0.06] flex flex-col animate-rail-slide-right">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-2">
            <Volume2 size={15} className="text-white/40" />
            <span className="text-sm font-semibold text-white/80">Meeting Voice</span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/5 text-white/30 hover:text-white/50 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto scrollbar-hide px-4 py-3 space-y-4">

          {/* ── TTS Toggle ── */}
          <div className="flex items-center justify-between py-2">
            <div>
              <div className="text-[11px] text-white/70 font-medium">Voice playback</div>
              <div className="text-[9px] text-white/30 mt-0.5">
                Speak persona replies aloud using browser TTS
              </div>
            </div>
            <button
              onClick={() => onToggleTts(!meetingTtsEnabled)}
              className={`relative w-9 h-5 rounded-full transition-colors ${
                meetingTtsEnabled
                  ? 'bg-emerald-500/25 border border-emerald-500/30'
                  : 'bg-white/[0.06] border border-white/[0.08]'
              }`}
            >
              <span
                className={`absolute top-0.5 w-4 h-4 rounded-full transition-all ${
                  meetingTtsEnabled
                    ? 'left-[18px] bg-emerald-300'
                    : 'left-0.5 bg-white/40'
                }`}
              />
            </button>
          </div>

          {/* ── Status pill ── */}
          <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-[10px] ${
            meetingTtsEnabled
              ? 'bg-emerald-500/[0.06] border-emerald-500/15 text-emerald-300/70'
              : 'bg-white/[0.02] border-white/[0.04] text-white/25'
          }`}>
            {meetingTtsEnabled ? <Volume2 size={11} /> : <VolumeX size={11} />}
            {meetingTtsEnabled ? 'Persona replies will be spoken aloud' : 'Voice playback disabled'}
          </div>

          {/* ── Per-persona voice pickers ── */}
          {meetingTtsEnabled && participants.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-2">
                Persona Voices ({participants.length})
              </div>

              {participants.map((p) => {
                const cfg = getPersonaVoice(p.id)
                const isAdvOpen = advancedOpen.has(p.id)
                return (
                  <div key={p.id} className="rounded-lg border border-white/[0.04] overflow-hidden">
                    {/* Voice picker row */}
                    <div className="px-3">
                      <PersonaVoicePicker
                        personaId={p.id}
                        label={p.name}
                        value={cfg}
                        onChange={(newCfg) => setPersonaVoice(p.id, newCfg)}
                      />
                    </div>

                    {/* Advanced toggle */}
                    <button
                      onClick={() => toggleAdvanced(p.id)}
                      className="w-full flex items-center gap-1 px-3 py-1 text-[9px] text-white/20 hover:text-white/35 transition-colors"
                    >
                      {isAdvOpen ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
                      Rate / Pitch
                    </button>

                    {/* Advanced sliders */}
                    {isAdvOpen && (
                      <div className="px-3 pb-2 space-y-2">
                        {/* Rate */}
                        <div>
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-[9px] text-white/25">Rate</span>
                            <span className="text-[9px] text-white/35 font-mono">{(cfg?.rate ?? 1.0).toFixed(2)}</span>
                          </div>
                          <input
                            type="range"
                            min={0.5}
                            max={2.0}
                            step={0.05}
                            value={cfg?.rate ?? 1.0}
                            onChange={(e) => setPersonaVoice(p.id, { ...(cfg || { voiceURI: '' }), rate: parseFloat(e.target.value) })}
                            className="w-full h-1 rounded-full bg-white/[0.06] appearance-none cursor-pointer accent-cyan-500 [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-2.5 [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:appearance-none"
                          />
                        </div>
                        {/* Pitch */}
                        <div>
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-[9px] text-white/25">Pitch</span>
                            <span className="text-[9px] text-white/35 font-mono">{(cfg?.pitch ?? 1.0).toFixed(2)}</span>
                          </div>
                          <input
                            type="range"
                            min={0.5}
                            max={2.0}
                            step={0.05}
                            value={cfg?.pitch ?? 1.0}
                            onChange={(e) => setPersonaVoice(p.id, { ...(cfg || { voiceURI: '' }), pitch: parseFloat(e.target.value) })}
                            className="w-full h-1 rounded-full bg-white/[0.06] appearance-none cursor-pointer accent-cyan-500 [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-2.5 [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:appearance-none"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* ── Help text ── */}
          <div className="px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
            <p className="text-[9px] text-white/20 leading-relaxed">
              Each persona can have a unique browser TTS voice. Voices vary by OS and browser.
              Use the preview button to test each voice before a meeting.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 px-4 py-3 border-t border-white/[0.06]">
          <button
            onClick={onClose}
            className="w-full px-3 py-2 rounded-lg bg-white/[0.04] hover:bg-white/[0.06] text-white/40 text-xs transition-colors"
          >
            Done
          </button>
        </div>
      </div>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  )
}
