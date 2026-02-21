/**
 * AvatarSettingsPanel — slide-out drawer for Avatar Studio model settings.
 *
 * Slides in from the right when the user clicks the gear icon.
 * Clean, enterprise-grade design that hides all checkpoint/model
 * complexity from beginners while giving power users full control.
 *
 * Persisted in localStorage under `homepilot_avatar_settings`.
 */

import React, { useState, useCallback, useEffect } from 'react'
import { Settings, X, Check, Globe, Sparkles, Info } from 'lucide-react'
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
 */
export function resolveCheckpoint(
  avatarSettings: AvatarSettings,
  globalModelImages?: string,
): string | undefined {
  if (avatarSettings.checkpointSource === 'global') {
    return globalModelImages || undefined
  }
  const rec = RECOMMENDED_CHECKPOINTS.find(
    (c) => c.id === avatarSettings.recommendedCheckpointId,
  )
  return rec?.filename
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarSettingsPanelProps {
  globalModelImages?: string
  settings: AvatarSettings
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

  return (
    <>
      {/* Gear icon trigger */}
      <button
        onClick={() => setOpen(true)}
        className="w-9 h-9 rounded-xl flex items-center justify-center transition-all border border-white/10 bg-white/5 text-white/40 hover:text-white/70 hover:bg-white/10 hover:border-white/20"
        title="Advanced Settings"
        aria-label="Open advanced settings"
      >
        <Settings size={16} />
      </button>

      {/* Backdrop + Drawer */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40"
            onClick={() => setOpen(false)}
          />

          {/* Slide-out drawer from right */}
          <div className="fixed top-0 right-0 bottom-0 w-full max-w-sm bg-[#111111] border-l border-white/10 z-50 flex flex-col animate-slideInRight">
            {/* Drawer header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
              <div>
                <h3 className="text-sm font-semibold text-white">Advanced Settings</h3>
                <p className="text-[10px] text-white/35 mt-0.5">
                  Configure the AI engine for avatar generation
                </p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 flex items-center justify-center text-white/40 hover:text-white/70 transition-colors"
                aria-label="Close settings"
              >
                <X size={16} />
              </button>
            </div>

            {/* Drawer body */}
            <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
              <div>
                <div className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
                  Model Configuration
                </div>
                <p className="text-[11px] text-white/30 mb-4">
                  Select the AI engine for your avatars
                </p>

                {/* Recommended option */}
                <button
                  onClick={() => setSource('recommended')}
                  className={[
                    'w-full flex items-start gap-3 px-4 py-3.5 rounded-xl text-left transition-all mb-2',
                    settings.checkpointSource === 'recommended'
                      ? 'bg-purple-500/10 border border-purple-500/30 ring-1 ring-purple-500/10'
                      : 'border border-white/8 hover:bg-white/[0.03] hover:border-white/15',
                  ].join(' ')}
                >
                  <div className="mt-0.5">
                    <Sparkles
                      size={16}
                      className={
                        settings.checkpointSource === 'recommended'
                          ? 'text-purple-400'
                          : 'text-white/25'
                      }
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white/80">
                        Recommended
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded-md bg-purple-500/20 text-purple-300 font-semibold">
                        Portrait Optimized
                      </span>
                    </div>
                    <p className="text-[11px] text-white/35 mt-1">
                      Curated models tuned for portrait generation
                    </p>
                  </div>
                  {settings.checkpointSource === 'recommended' && (
                    <Check size={16} className="text-purple-400 mt-0.5 shrink-0" />
                  )}
                </button>

                {/* Recommended checkpoint selector */}
                {settings.checkpointSource === 'recommended' && (
                  <div className="ml-8 mb-3 space-y-1.5">
                    {RECOMMENDED_CHECKPOINTS.map((ckpt) => (
                      <button
                        key={ckpt.id}
                        onClick={() => setRecommended(ckpt.id)}
                        className={[
                          'w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-left transition-all',
                          settings.recommendedCheckpointId === ckpt.id
                            ? 'bg-white/8 border border-white/15'
                            : 'border border-transparent hover:bg-white/[0.04]',
                        ].join(' ')}
                      >
                        <div>
                          <div className="text-xs font-medium text-white/70">
                            {ckpt.label}
                          </div>
                          <div className="text-[10px] text-white/30 mt-0.5">
                            {ckpt.description}
                          </div>
                        </div>
                        {settings.recommendedCheckpointId === ckpt.id && (
                          <Check size={14} className="text-green-400 shrink-0 ml-2" />
                        )}
                      </button>
                    ))}
                  </div>
                )}

                {/* Global Settings option */}
                <button
                  onClick={() => setSource('global')}
                  className={[
                    'w-full flex items-start gap-3 px-4 py-3.5 rounded-xl text-left transition-all',
                    settings.checkpointSource === 'global'
                      ? 'bg-blue-500/10 border border-blue-500/30 ring-1 ring-blue-500/10'
                      : 'border border-white/8 hover:bg-white/[0.03] hover:border-white/15',
                  ].join(' ')}
                >
                  <div className="mt-0.5">
                    <Globe
                      size={16}
                      className={
                        settings.checkpointSource === 'global'
                          ? 'text-blue-400'
                          : 'text-white/25'
                      }
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white/80">
                      Global Settings
                    </div>
                    <p className="text-[11px] text-white/35 mt-1">
                      Use the Image Model from your main Settings panel
                    </p>
                    {settings.checkpointSource === 'global' && globalModelImages && (
                      <div className="text-[10px] text-blue-400/70 mt-1.5 font-mono truncate">
                        {globalModelImages}
                      </div>
                    )}
                  </div>
                  {settings.checkpointSource === 'global' && (
                    <Check size={16} className="text-blue-400 mt-0.5 shrink-0" />
                  )}
                </button>

                {settings.checkpointSource === 'global' && (
                  <div className="flex items-start gap-2 mt-3 ml-8 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10">
                    <Info size={12} className="text-amber-400/60 mt-0.5 shrink-0" />
                    <p className="text-[10px] text-amber-300/50 leading-relaxed">
                      May not be optimized for portrait generation
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Drawer footer */}
            <div className="px-5 py-4 border-t border-white/8">
              <button
                onClick={() => setOpen(false)}
                className="w-full py-2.5 rounded-xl bg-white/10 hover:bg-white/15 text-sm font-medium text-white/80 transition-colors"
              >
                Save &amp; Close
              </button>
              <div className="mt-3 text-center">
                <span className="text-[9px] text-white/25 uppercase tracking-wider">Active: </span>
                <span className="text-[10px] text-white/40 font-mono">
                  {currentRec?.label || globalModelImages || 'Default'}
                </span>
              </div>
            </div>
          </div>
        </>
      )}

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slideInRight {
          animation: slideInRight 0.25s ease-out;
        }
      `}</style>
    </>
  )
}
