/**
 * AvatarSettingsPanel — gear icon popover for Avatar Studio model settings.
 *
 * Lets the user choose between:
 *   - Recommended (default): curated portrait-optimised checkpoints
 *   - Global Settings: inherit the checkpoint from the main Settings panel
 *
 * Persisted in localStorage under `homepilot_avatar_settings`.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react'
import { Settings, ChevronDown, Check, Globe, Sparkles, Info } from 'lucide-react'
import type { AvatarSettings, AvatarCheckpointSource } from './types'
import { RECOMMENDED_CHECKPOINTS } from './types'

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'homepilot_avatar_settings'

const DEFAULT_SETTINGS: AvatarSettings = {
  checkpointSource: 'recommended',
  recommendedCheckpointId: 'dreamshaper8',
}

export function loadAvatarSettings(): AvatarSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return { ...DEFAULT_SETTINGS, ...parsed }
    }
  } catch { /* ignore */ }
  return { ...DEFAULT_SETTINGS }
}

export function saveAvatarSettings(s: AvatarSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
  } catch { /* ignore */ }
}

/**
 * Resolve the effective checkpoint filename based on current avatar settings
 * and the global settings model.
 *
 * Returns `undefined` when no override should be sent (workflow keeps its
 * built-in default).
 */
export function resolveCheckpoint(
  avatarSettings: AvatarSettings,
  globalModelImages?: string,
): string | undefined {
  if (avatarSettings.checkpointSource === 'global') {
    return globalModelImages || undefined
  }
  // 'recommended'
  const rec = RECOMMENDED_CHECKPOINTS.find(
    (c) => c.id === avatarSettings.recommendedCheckpointId,
  )
  return rec?.filename
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarSettingsPanelProps {
  /** The global model from Settings (settingsDraft.modelImages) */
  globalModelImages?: string
  /** Current avatar settings (lifted state) */
  settings: AvatarSettings
  /** Called when user changes avatar settings */
  onChange: (next: AvatarSettings) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AvatarSettingsPanel({
  globalModelImages,
  settings,
  onChange,
}: AvatarSettingsPanelProps) {
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  const setSource = useCallback(
    (source: AvatarCheckpointSource) => {
      const next = { ...settings, checkpointSource: source }
      onChange(next)
      saveAvatarSettings(next)
    },
    [settings, onChange],
  )

  const setRecommended = useCallback(
    (id: string) => {
      const next = {
        ...settings,
        checkpointSource: 'recommended' as const,
        recommendedCheckpointId: id,
      }
      onChange(next)
      saveAvatarSettings(next)
    },
    [settings, onChange],
  )

  const currentRec = RECOMMENDED_CHECKPOINTS.find(
    (c) => c.id === settings.recommendedCheckpointId,
  )

  const effectiveModel =
    settings.checkpointSource === 'global'
      ? globalModelImages || 'Not set — using workflow default'
      : currentRec?.filename || 'dreamshaper_8.safetensors'

  return (
    <div className="relative" ref={panelRef}>
      {/* Gear icon button */}
      <button
        onClick={() => setOpen(!open)}
        className={[
          'p-1.5 rounded-lg transition-all',
          open
            ? 'bg-purple-500/15 text-purple-400'
            : 'text-white/30 hover:text-white/60 hover:bg-white/5',
        ].join(' ')}
        title="Avatar model settings"
        aria-label="Avatar model settings"
        aria-expanded={open}
      >
        <Settings size={16} />
      </button>

      {/* Popover */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-xl bg-[#1a1a1a] border border-white/10 shadow-2xl z-50 overflow-hidden animate-fadeIn">
          {/* Header */}
          <div className="px-4 py-3 border-b border-white/5">
            <div className="text-xs font-semibold text-white/80">Model Settings</div>
            <div className="text-[10px] text-white/35 mt-0.5">
              Choose which checkpoint Avatar Studio uses
            </div>
          </div>

          {/* Source selector */}
          <div className="p-3 space-y-1.5">
            {/* Recommended option */}
            <button
              onClick={() => setSource('recommended')}
              className={[
                'w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-all',
                settings.checkpointSource === 'recommended'
                  ? 'bg-purple-500/10 border border-purple-500/30'
                  : 'border border-transparent hover:bg-white/5',
              ].join(' ')}
            >
              <div className="mt-0.5">
                <Sparkles
                  size={14}
                  className={
                    settings.checkpointSource === 'recommended'
                      ? 'text-purple-400'
                      : 'text-white/30'
                  }
                />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-white/80">
                    Recommended
                  </span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-medium">
                    Default
                  </span>
                </div>
                <div className="text-[10px] text-white/40 mt-0.5">
                  Portrait-optimised models curated for avatars
                </div>
              </div>
              {settings.checkpointSource === 'recommended' && (
                <Check size={14} className="text-purple-400 mt-0.5 shrink-0" />
              )}
            </button>

            {/* Global Settings option */}
            <button
              onClick={() => setSource('global')}
              className={[
                'w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-all',
                settings.checkpointSource === 'global'
                  ? 'bg-blue-500/10 border border-blue-500/30'
                  : 'border border-transparent hover:bg-white/5',
              ].join(' ')}
            >
              <div className="mt-0.5">
                <Globe
                  size={14}
                  className={
                    settings.checkpointSource === 'global'
                      ? 'text-blue-400'
                      : 'text-white/30'
                  }
                />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-white/80">
                  Global Settings
                </div>
                <div className="text-[10px] text-white/40 mt-0.5">
                  Use the Image Model from your main Settings
                </div>
                {settings.checkpointSource === 'global' && globalModelImages && (
                  <div className="text-[10px] text-blue-400/70 mt-1 font-mono truncate">
                    {globalModelImages}
                  </div>
                )}
              </div>
              {settings.checkpointSource === 'global' && (
                <Check size={14} className="text-blue-400 mt-0.5 shrink-0" />
              )}
            </button>
          </div>

          {/* Recommended checkpoint list (only when source = 'recommended') */}
          {settings.checkpointSource === 'recommended' && (
            <div className="px-3 pb-3">
              <div className="text-[10px] text-white/30 uppercase tracking-wider font-medium mb-1.5 px-1">
                Select Model
              </div>
              <div className="space-y-1">
                {RECOMMENDED_CHECKPOINTS.map((ckpt) => (
                  <button
                    key={ckpt.id}
                    onClick={() => setRecommended(ckpt.id)}
                    className={[
                      'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-all',
                      settings.recommendedCheckpointId === ckpt.id
                        ? 'bg-white/8 border border-white/15'
                        : 'border border-transparent hover:bg-white/5',
                    ].join(' ')}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] font-medium text-white/70">
                        {ckpt.label}
                      </div>
                      <div className="text-[9px] text-white/30 mt-0.5">
                        {ckpt.description}
                      </div>
                    </div>
                    {settings.recommendedCheckpointId === ckpt.id && (
                      <Check size={12} className="text-green-400 shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Info footer */}
          <div className="px-4 py-2.5 border-t border-white/5 bg-white/[0.02]">
            <div className="flex items-start gap-2">
              <Info size={11} className="text-white/25 mt-0.5 shrink-0" />
              <div className="text-[9px] text-white/30 leading-relaxed">
                {settings.checkpointSource === 'recommended' ? (
                  <>These models are tuned for portrait generation. For other styles or NSFW models, switch to Global Settings.</>
                ) : (
                  <>Using your globally configured Image Model. Change it in the main Settings panel. Some models may not be optimised for portraits.</>
                )}
              </div>
            </div>
          </div>

          {/* Active model indicator */}
          <div className="px-4 py-2 border-t border-white/5">
            <div className="text-[9px] text-white/25 uppercase tracking-wider mb-1">
              Active Model
            </div>
            <div className="text-[10px] text-white/50 font-mono truncate">
              {effectiveModel}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
