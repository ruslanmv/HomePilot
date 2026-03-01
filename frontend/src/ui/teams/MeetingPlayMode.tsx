/**
 * MeetingPlayMode — Configuration-only panel for Play Mode.
 *
 * This is purely the setup panel (style, interval, rounds, start).
 * Once Play Mode is active, the panel auto-closes and all controls
 * move to the inline control strip in MeetingRoom (single source of truth).
 *
 * Design: purple Gamepad2 theme, matching Game Mode in Imagine.
 */

import React, { useState, useEffect } from 'react'
import {
  Gamepad2,
  Play,
  X,
  Zap,
  MessageSquare,
  Swords,
  Circle,
  Drama,
  FlaskConical,
} from 'lucide-react'
import type { PlayModeStyle, PlayModeState } from './types'


// ---------------------------------------------------------------------------
// Style presets
// ---------------------------------------------------------------------------

const STYLE_OPTIONS: Array<{
  value: PlayModeStyle
  label: string
  desc: string
  icon: React.ReactNode
}> = [
  { value: 'discussion', label: 'Discussion', desc: 'Natural multi-speaker conversation', icon: <MessageSquare size={14} /> },
  { value: 'debate', label: 'Debate', desc: 'Alternating speakers, high diversity', icon: <Swords size={14} /> },
  { value: 'roundtable', label: 'Roundtable', desc: 'Everyone speaks once per cycle', icon: <Circle size={14} /> },
  { value: 'roleplay', label: 'Roleplay', desc: 'Amplified personality, creative flow', icon: <Drama size={14} /> },
  { value: 'simulation', label: 'Simulation', desc: 'Scenario-driven extended session', icon: <FlaskConical size={14} /> },
]

const INTERVAL_PRESETS = [
  { value: 2000, label: '2s' },
  { value: 3000, label: '3s' },
  { value: 5000, label: '5s' },
  { value: 8000, label: '8s' },
]

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MeetingPlayModeProps {
  playMode: PlayModeState | undefined
  participantCount: number
  turnMode?: 'reactive' | 'round-robin' | 'free-form' | 'moderated'
  onStart: (opts: { style: PlayModeStyle; interval_ms: number; max_rounds: number }) => Promise<void>
  onStop: () => Promise<void>
  onPause: () => Promise<void>
  onResume: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MeetingPlayMode({
  playMode,
  participantCount,
  turnMode = 'reactive',
  onStart,
  onStop,
  onPause,
  onResume,
}: MeetingPlayModeProps) {
  const [panelOpen, setPanelOpen] = useState(false)
  const [style, setStyle] = useState<PlayModeStyle>(playMode?.style || 'discussion')
  const [intervalMs, setIntervalMs] = useState(playMode?.interval_ms || 3000)
  const [maxRounds, setMaxRounds] = useState(playMode?.max_rounds || 50)
  const [infinite, setInfinite] = useState((playMode?.max_rounds || 0) === 0)
  const [starting, setStarting] = useState(false)

  const isActive = playMode?.enabled === true

  // Auto-close panel when play mode starts
  useEffect(() => {
    if (isActive) setPanelOpen(false)
  }, [isActive])

  const handleStart = async () => {
    setStarting(true)
    try {
      await onStart({ style, interval_ms: intervalMs, max_rounds: infinite ? 0 : maxRounds })
      setPanelOpen(false) // close immediately
    } catch (e) {
      console.error('Failed to start play mode:', e)
    } finally {
      setStarting(false)
    }
  }

  const canStart = participantCount >= 2

  return (
    <div className="relative">
      {/* ── Toggle Button ── */}
      <button
        onClick={() => setPanelOpen(!panelOpen)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all border ${
          isActive
            ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
            : panelOpen
              ? 'bg-purple-500/10 border-purple-500/30 text-purple-300/80'
              : 'bg-white/[0.03] hover:bg-white/[0.06] border-white/[0.06] hover:border-white/12 text-white/40 hover:text-white/60'
        }`}
        title="Play Mode — autonomous AI conversation"
      >
        <Gamepad2 size={14} />
        {isActive && (
          <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-glow-pulse" />
        )}
      </button>

      {/* ── Config Panel (only when NOT active) ── */}
      {panelOpen && !isActive && (
        <div className="absolute top-full right-0 mt-2 w-80 rounded-2xl bg-black/95 backdrop-blur-xl border border-white/10 shadow-2xl z-50 p-5 animate-msg-slide-in">

          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Gamepad2 size={16} className="text-purple-400" />
              <span className="text-sm font-bold text-white">Play Mode</span>
            </div>
            <button
              onClick={() => setPanelOpen(false)}
              className="p-1 rounded-lg hover:bg-white/5 text-white/30 hover:text-white/60 transition-colors"
            >
              <X size={14} />
            </button>
          </div>

          {/* Description (mode-aware) */}
          <p className="text-[11px] text-white/30 mb-4 leading-relaxed">
            {turnMode === 'round-robin'
              ? 'Personas converse autonomously in initiative order (round-robin). You are an observer — join anytime by sending a message.'
              : 'Personas converse autonomously. The system selects speakers based on relevance. You are an observer — join anytime by sending a message.'}
          </p>

          {/* Configuration form */}
          <div className="space-y-4">

            {/* Method indicator */}
            <div>
              <label className="text-[11px] text-white/40 font-medium mb-1 block">Method</label>
              <div className="px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.04] text-[10px] text-purple-300/60">
                {turnMode === 'round-robin' ? 'Initiative (Round-robin)' : 'Reactive (Intent-based)'}
              </div>
            </div>

            {/* Style selector (only for reactive mode — styles tune the reactive orchestrator) */}
            {turnMode !== 'round-robin' && (
            <div>
              <label className="text-[11px] text-white/40 font-medium mb-2 block">
                Conversation Style
                <span className="text-[9px] text-white/15 ml-1.5">Tunes the reactive orchestrator</span>
              </label>
              <div className="space-y-1.5">
                {STYLE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setStyle(opt.value)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all ${
                      style === opt.value
                        ? 'bg-purple-500/20 border border-purple-500/30 text-purple-300'
                        : 'bg-white/[0.02] border border-white/[0.04] text-white/50 hover:bg-white/[0.04] hover:text-white/70'
                    }`}
                  >
                    <span className={style === opt.value ? 'text-purple-400' : 'text-white/30'}>{opt.icon}</span>
                    <div>
                      <div className="text-xs font-medium">{opt.label}</div>
                      <div className="text-[10px] text-white/30">{opt.desc}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
            )}

            {/* Initiative mode info */}
            {turnMode === 'round-robin' && (
            <div className="px-2.5 py-2 rounded-lg bg-purple-500/5 border border-purple-500/10">
              <p className="text-[10px] text-purple-300/40 leading-relaxed">
                In Initiative mode, personas speak in fixed turn order.
                Conversation styles are not available — switch to Reactive mode in Room Settings to use styles.
              </p>
            </div>
            )}

            {/* Interval */}
            <div>
              <label className="text-[11px] text-white/40 font-medium mb-2 block">Step Interval</label>
              <div className="flex items-center gap-1.5">
                {INTERVAL_PRESETS.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => setIntervalMs(p.value)}
                    className={`flex-1 px-2 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      intervalMs === p.value
                        ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                        : 'bg-white/[0.03] text-white/40 border border-white/[0.04] hover:bg-white/[0.06]'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Max Rounds */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11px] text-white/40 font-medium">Max Rounds</label>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setInfinite(!infinite)}
                    className={`text-[10px] px-1.5 py-0.5 rounded-md font-medium transition-all ${
                      infinite
                        ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                        : 'bg-white/[0.03] text-white/30 border border-white/[0.06] hover:text-white/50'
                    }`}
                  >
                    ∞
                  </button>
                  <span className="text-[11px] text-purple-300/60 font-mono">
                    {infinite ? '∞' : maxRounds}
                  </span>
                </div>
              </div>
              {!infinite && (
                <input
                  type="range"
                  min={5}
                  max={200}
                  step={5}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Number(e.target.value))}
                  className="w-full h-1 rounded-full appearance-none bg-white/[0.06] accent-purple-500 cursor-pointer
                    [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                    [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:shadow-md"
                />
              )}
            </div>

            {/* Start button */}
            <button
              onClick={handleStart}
              disabled={!canStart || starting}
              className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
                canStart && !starting
                  ? 'bg-purple-500/25 hover:bg-purple-500/35 text-purple-200 border border-purple-500/40'
                  : 'bg-white/[0.02] text-white/15 border border-white/[0.04] cursor-not-allowed'
              }`}
            >
              {starting ? (
                <>
                  <Zap size={14} className="animate-glow-pulse" />
                  Starting...
                </>
              ) : (
                <>
                  <Play size={14} />
                  Start Play Mode
                </>
              )}
            </button>

            {!canStart && (
              <p className="text-[10px] text-red-300/50 text-center">
                Need at least 2 participants to start Play Mode
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
