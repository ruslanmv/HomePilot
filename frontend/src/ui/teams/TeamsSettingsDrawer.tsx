/**
 * TeamsSettingsDrawer — Slide-out settings panel for meeting room configuration.
 *
 * Sections:
 *   - General:       Room name, description, turn mode
 *   - Orchestration:  Speak/hand-raise thresholds, max speakers, cooldown
 *   - LLM & Perf:    Provider, model, concurrency, timeout
 *   - View:          Layout, labels, animation toggles
 *   - Advanced:      Memory depth, federation
 *
 * Additive — rendered in MeetingRoom as a slide-over panel.
 * UI-only by default; changes are local state until onSave is called.
 */

import React, { useState, useCallback, useEffect } from 'react'
import {
  X,
  Settings,
  ChevronDown,
  ChevronRight,
  Sliders,
  Cpu,
  Eye,
  Wrench,
  Info,
} from 'lucide-react'
import type { MeetingRoom, TeamsRoomPolicy } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TeamsSettingsDrawerProps {
  room: MeetingRoom
  open: boolean
  onClose: () => void
  /** If provided, enables the Save button. Called with the draft policy. */
  onSave?: (policy: TeamsRoomPolicy) => void
  /** Called when the user switches turn mode (Reactive / Initiative). */
  onChangeTurnMode?: (turnMode: 'reactive' | 'round-robin') => Promise<void>
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

/** Read global LLM settings from localStorage (same keys as SettingsPanel / App.tsx). */
function readGlobalLLMSettings(): Pick<TeamsRoomPolicy, 'llm_provider' | 'llm_model' | 'llm_base_url' | 'llm_concurrency'> {
  try {
    const provider = localStorage.getItem('homepilot_provider_chat') || localStorage.getItem('homepilot_provider') || 'ollama'
    const model = localStorage.getItem('homepilot_model_chat') || localStorage.getItem('homepilot_ollama_model') || ''
    const base_url = localStorage.getItem('homepilot_base_url_chat') || localStorage.getItem('homepilot_ollama_url') || ''
    const concRaw = localStorage.getItem('homepilot_teams_concurrent_calls')
    const concurrency = concRaw ? parseInt(concRaw, 10) : 2
    return { llm_provider: provider, llm_model: model, llm_base_url: base_url, llm_concurrency: concurrency }
  } catch {
    return { llm_provider: 'ollama', llm_model: '', llm_base_url: '', llm_concurrency: 2 }
  }
}

const DEFAULT_POLICY: TeamsRoomPolicy = {
  max_speakers_per_event: 3,
  max_rounds_per_event: 5,
  speak_threshold: 0.45,
  cooldown_turns: 1,
  hand_raise_threshold: 0.3,
  hand_raise_ttl_rounds: 3,
  max_visible_hands: 4,
  redundancy_threshold: 0.85,
  dominance_lookback: 8,
  dominance_penalty: 0.15,
  llm_provider: 'ollama',
  llm_model: '',
  llm_base_url: '',
  llm_concurrency: 2,
  llm_timeout_secs: 60,
  view_layout: 'oval',
  view_show_labels: true,
  view_show_animations: true,
  memory_depth: 50,
}

// ---------------------------------------------------------------------------
// Section collapse helper
// ---------------------------------------------------------------------------

type SectionId = 'general' | 'orchestration' | 'llm' | 'view' | 'advanced'

const SECTIONS: Array<{ id: SectionId; label: string; icon: React.ReactNode }> = [
  { id: 'general', label: 'General', icon: <Settings size={13} /> },
  { id: 'orchestration', label: 'Orchestration', icon: <Sliders size={13} /> },
  { id: 'llm', label: 'LLM & Performance', icon: <Cpu size={13} /> },
  { id: 'view', label: 'View', icon: <Eye size={13} /> },
  { id: 'advanced', label: 'Advanced', icon: <Wrench size={13} /> },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TeamsSettingsDrawer({ room, open, onClose, onSave, onChangeTurnMode }: TeamsSettingsDrawerProps) {
  const [expandedSections, setExpandedSections] = useState<Set<SectionId>>(new Set(['general']))
  const [draft, setDraft] = useState<TeamsRoomPolicy>({ ...DEFAULT_POLICY })

  // Sync draft from room.policy + global LLM settings when drawer opens
  useEffect(() => {
    if (open) {
      const globalLLM = readGlobalLLMSettings()
      setDraft((prev) => ({
        ...DEFAULT_POLICY,
        ...globalLLM, // Global settings as base for LLM fields
        ...prev,
        ...(room.policy || {}), // Room-level overrides take precedence
      }))
    }
  }, [open, room.policy])

  const toggleSection = useCallback((id: SectionId) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const updateDraft = useCallback(<K extends keyof TeamsRoomPolicy>(key: K, value: TeamsRoomPolicy[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }))
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
            <Settings size={15} className="text-white/40" />
            <span className="text-sm font-semibold text-white/80">Room Settings</span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/5 text-white/30 hover:text-white/50 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto scrollbar-hide px-4 py-3 space-y-1">
          {SECTIONS.map((section) => {
            const expanded = expandedSections.has(section.id)
            return (
              <div key={section.id} className="rounded-lg border border-white/[0.04] overflow-hidden">
                {/* Section header */}
                <button
                  onClick={() => toggleSection(section.id)}
                  className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-white/[0.02] transition-colors"
                >
                  {expanded ? (
                    <ChevronDown size={12} className="text-white/25" />
                  ) : (
                    <ChevronRight size={12} className="text-white/25" />
                  )}
                  <span className="text-white/35">{section.icon}</span>
                  <span className="text-xs font-medium text-white/55">{section.label}</span>
                </button>

                {/* Section body */}
                {expanded && (
                  <div className="px-3 pb-3 space-y-3">
                    {section.id === 'general' && (
                      <GeneralSection room={room} onChangeTurnMode={onChangeTurnMode} />
                    )}
                    {section.id === 'orchestration' && (
                      <OrchestrationSection draft={draft} onChange={updateDraft} />
                    )}
                    {section.id === 'llm' && (
                      <LLMSection draft={draft} onChange={updateDraft} />
                    )}
                    {section.id === 'view' && (
                      <ViewSection draft={draft} onChange={updateDraft} />
                    )}
                    {section.id === 'advanced' && (
                      <AdvancedSection draft={draft} onChange={updateDraft} />
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 px-4 py-3 border-t border-white/[0.06] flex items-center gap-2">
          {onSave ? (
            <button
              onClick={() => onSave(draft)}
              className="flex-1 px-3 py-2 rounded-lg bg-cyan-600/80 hover:bg-cyan-500 text-white text-xs font-medium transition-colors"
            >
              Save Settings
            </button>
          ) : (
            <div className="flex items-center gap-1.5 text-[10px] text-white/20">
              <Info size={10} />
              <span>Settings are UI-preview only in this release</span>
            </div>
          )}
          <button
            onClick={onClose}
            className="px-3 py-2 rounded-lg bg-white/[0.04] hover:bg-white/[0.06] text-white/40 text-xs transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section sub-components
// ---------------------------------------------------------------------------

function FieldLabel({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="mb-1">
      <span className="text-[10px] font-medium text-white/35">{label}</span>
      {hint && <span className="text-[9px] text-white/15 ml-1.5">{hint}</span>}
    </div>
  )
}

function SliderField({
  label,
  hint,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string
  hint?: string
  value: number
  min: number
  max: number
  step: number
  format?: (v: number) => string
  onChange: (v: number) => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <FieldLabel label={label} hint={hint} />
        <span className="text-[10px] text-white/40 font-mono">{format ? format(value) : value}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1 rounded-full bg-white/[0.06] appearance-none cursor-pointer accent-cyan-500 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:appearance-none"
      />
    </div>
  )
}

function TextInput({
  label,
  hint,
  value,
  placeholder,
  onChange,
}: {
  label: string
  hint?: string
  value: string
  placeholder?: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <FieldLabel label={label} hint={hint} />
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.06] text-[10px] text-white/60 placeholder:text-white/15 focus:outline-none focus:border-cyan-500/30 transition-colors"
      />
    </div>
  )
}

function ToggleField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint?: string
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between">
      <FieldLabel label={label} hint={hint} />
      <button
        onClick={() => onChange(!value)}
        className={`relative w-8 h-4.5 rounded-full transition-colors ${
          value ? 'bg-cyan-500/40' : 'bg-white/[0.08]'
        }`}
      >
        <span
          className={`absolute top-0.5 w-3.5 h-3.5 rounded-full transition-all ${
            value ? 'left-4 bg-cyan-400' : 'left-0.5 bg-white/30'
          }`}
        />
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section: General (read-only room info)
// ---------------------------------------------------------------------------

function GeneralSection({ room, onChangeTurnMode }: { room: MeetingRoom; onChangeTurnMode?: (turnMode: 'reactive' | 'round-robin') => Promise<void> }) {
  const [switching, setSwitching] = useState(false)

  const TURN_MODES = [
    { value: 'reactive' as const, label: 'Reactive', desc: 'Orchestrator selects speakers by relevance' },
    { value: 'round-robin' as const, label: 'Initiative', desc: 'Fixed turn order (BG3-style)' },
  ]

  const handleSwitch = async (mode: 'reactive' | 'round-robin') => {
    if (mode === room.turn_mode || !onChangeTurnMode || switching) return
    setSwitching(true)
    try {
      await onChangeTurnMode(mode)
    } catch (e) {
      console.warn('Failed to switch turn mode:', e)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <>
      <div>
        <FieldLabel label="Room Name" />
        <div className="px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.04] text-[10px] text-white/50">
          {room.name}
        </div>
      </div>
      {room.description && (
        <div>
          <FieldLabel label="Description" />
          <div className="px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.04] text-[10px] text-white/40 leading-relaxed">
            {room.description}
          </div>
        </div>
      )}
      <div>
        <FieldLabel label="Conversation Mode" hint="How speakers are selected" />
        <div className="flex gap-1.5">
          {TURN_MODES.map((mode) => (
            <button
              key={mode.value}
              onClick={() => handleSwitch(mode.value)}
              disabled={switching}
              className={`flex-1 px-2.5 py-2 rounded-lg text-left transition-all border ${
                room.turn_mode === mode.value
                  ? 'bg-cyan-500/10 border-cyan-500/20 text-cyan-300'
                  : 'bg-white/[0.03] border-white/[0.06] text-white/30 hover:text-white/50 cursor-pointer'
              } ${switching ? 'opacity-50' : ''}`}
              title={mode.desc}
            >
              <div className="text-[10px] font-medium">{mode.label}</div>
              <div className="text-[9px] text-white/20 mt-0.5">{mode.desc}</div>
            </button>
          ))}
        </div>
        <p className="text-[9px] text-white/15 mt-1">
          {room.turn_mode === 'reactive'
            ? 'Intent scoring, hand-raise, and gates decide who speaks.'
            : 'Deterministic turn order — one speaker per click.'}
        </p>
      </div>
      <div>
        <FieldLabel label="Participants" />
        <div className="px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.04] text-[10px] text-white/50">
          {room.participant_ids.length} persona(s) + You
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Section: Orchestration
// ---------------------------------------------------------------------------

type DraftUpdater = <K extends keyof TeamsRoomPolicy>(key: K, value: TeamsRoomPolicy[K]) => void

function OrchestrationSection({ draft, onChange }: { draft: TeamsRoomPolicy; onChange: DraftUpdater }) {
  return (
    <>
      <SliderField
        label="Speak Threshold"
        hint="Confidence needed to speak"
        value={draft.speak_threshold ?? 0.45}
        min={0.1}
        max={0.9}
        step={0.05}
        format={(v) => v.toFixed(2)}
        onChange={(v) => onChange('speak_threshold', v)}
      />
      <SliderField
        label="Hand-Raise Threshold"
        hint="Confidence to raise hand"
        value={draft.hand_raise_threshold ?? 0.3}
        min={0.1}
        max={0.8}
        step={0.05}
        format={(v) => v.toFixed(2)}
        onChange={(v) => onChange('hand_raise_threshold', v)}
      />
      <SliderField
        label="Hand-Raise TTL"
        hint="Rounds before auto-lower"
        value={draft.hand_raise_ttl_rounds ?? 3}
        min={1}
        max={10}
        step={1}
        onChange={(v) => onChange('hand_raise_ttl_rounds', v)}
      />
      <SliderField
        label="Max Speakers / Event"
        value={draft.max_speakers_per_event ?? 3}
        min={1}
        max={8}
        step={1}
        onChange={(v) => onChange('max_speakers_per_event', v)}
      />
      <SliderField
        label="Max Rounds / Event"
        value={draft.max_rounds_per_event ?? 5}
        min={1}
        max={15}
        step={1}
        onChange={(v) => onChange('max_rounds_per_event', v)}
      />
      <SliderField
        label="Cooldown Turns"
        hint="Turns before re-speaking"
        value={draft.cooldown_turns ?? 1}
        min={0}
        max={5}
        step={1}
        onChange={(v) => onChange('cooldown_turns', v)}
      />
      <SliderField
        label="Redundancy Threshold"
        hint="Skip if too similar to prior"
        value={draft.redundancy_threshold ?? 0.85}
        min={0.5}
        max={1.0}
        step={0.05}
        format={(v) => v.toFixed(2)}
        onChange={(v) => onChange('redundancy_threshold', v)}
      />
      <SliderField
        label="Dominance Lookback"
        hint="Messages to check"
        value={draft.dominance_lookback ?? 8}
        min={3}
        max={20}
        step={1}
        onChange={(v) => onChange('dominance_lookback', v)}
      />
      <SliderField
        label="Dominance Penalty"
        value={draft.dominance_penalty ?? 0.15}
        min={0}
        max={0.5}
        step={0.05}
        format={(v) => v.toFixed(2)}
        onChange={(v) => onChange('dominance_penalty', v)}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Section: LLM & Performance
// ---------------------------------------------------------------------------

function LLMSection({ draft, onChange }: { draft: TeamsRoomPolicy; onChange: DraftUpdater }) {
  const syncFromGlobal = () => {
    const global = readGlobalLLMSettings()
    onChange('llm_provider', global.llm_provider ?? 'ollama')
    onChange('llm_model', global.llm_model ?? '')
    onChange('llm_base_url', global.llm_base_url ?? '')
    onChange('llm_concurrency', global.llm_concurrency ?? 2)
  }

  return (
    <>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <Info size={9} className="text-cyan-400/40" />
          <span className="text-[9px] text-cyan-300/40">Synced from Global Settings</span>
        </div>
        <button
          onClick={syncFromGlobal}
          className="text-[9px] text-cyan-300/40 hover:text-cyan-300/70 transition-colors"
        >
          Re-sync
        </button>
      </div>
      <TextInput
        label="LLM Provider"
        hint="e.g. ollama, openai"
        value={draft.llm_provider ?? 'ollama'}
        placeholder="ollama"
        onChange={(v) => onChange('llm_provider', v)}
      />
      <TextInput
        label="Model Name"
        hint="e.g. llama3, gpt-4o"
        value={draft.llm_model ?? ''}
        placeholder="(use global setting)"
        onChange={(v) => onChange('llm_model', v)}
      />
      <TextInput
        label="Base URL"
        hint="Override endpoint"
        value={draft.llm_base_url ?? ''}
        placeholder="(use global setting)"
        onChange={(v) => onChange('llm_base_url', v)}
      />
      <SliderField
        label="Concurrency"
        hint="Parallel LLM calls"
        value={draft.llm_concurrency ?? 2}
        min={1}
        max={5}
        step={1}
        onChange={(v) => onChange('llm_concurrency', v)}
      />
      <SliderField
        label="Timeout"
        hint="Seconds per LLM call"
        value={draft.llm_timeout_secs ?? 60}
        min={10}
        max={300}
        step={10}
        format={(v) => `${v}s`}
        onChange={(v) => onChange('llm_timeout_secs', v)}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Section: View
// ---------------------------------------------------------------------------

function ViewSection({ draft, onChange }: { draft: TeamsRoomPolicy; onChange: DraftUpdater }) {
  return (
    <>
      <div>
        <FieldLabel label="Table Layout" />
        <div className="flex gap-1.5">
          {(['oval', 'grid'] as const).map((layout) => (
            <button
              key={layout}
              onClick={() => onChange('view_layout', layout)}
              className={`flex-1 px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-colors ${
                draft.view_layout === layout
                  ? 'bg-cyan-500/10 border-cyan-500/20 text-cyan-300'
                  : 'bg-white/[0.03] border-white/[0.06] text-white/30 hover:text-white/50'
              }`}
            >
              {layout.charAt(0).toUpperCase() + layout.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <ToggleField
        label="Show Labels"
        hint="Status text under seats"
        value={draft.view_show_labels ?? true}
        onChange={(v) => onChange('view_show_labels', v)}
      />
      <ToggleField
        label="Show Animations"
        hint="Glow, pulse, equalizer"
        value={draft.view_show_animations ?? true}
        onChange={(v) => onChange('view_show_animations', v)}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Section: Advanced
// ---------------------------------------------------------------------------

function AdvancedSection({ draft, onChange }: { draft: TeamsRoomPolicy; onChange: DraftUpdater }) {
  return (
    <>
      <SliderField
        label="Memory Depth"
        hint="Messages each participant reads from chat history"
        value={draft.memory_depth ?? 50}
        min={5}
        max={200}
        step={5}
        onChange={(v) => onChange('memory_depth', v)}
      />
      <div className="mt-2 px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
        <div className="flex items-center gap-1.5 mb-1">
          <Info size={10} className="text-white/20" />
          <span className="text-[9px] text-white/25 font-medium">Federation</span>
        </div>
        <p className="text-[9px] text-white/15 leading-relaxed">
          Cross-room federation is planned for a future release.
          Personas will be able to join meetings from external HomePilot instances.
        </p>
      </div>
    </>
  )
}
