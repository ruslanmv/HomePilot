/**
 * LoraManager — Lightweight LoRA toggle + weight control for the Edit page.
 *
 * Additive component (Golden Rule 1.0).
 * Does NOT modify any existing Edit tab logic — it just provides state
 * that the parent can read and pass into the edit message flags.
 *
 * Features:
 * - Fetches installed LoRAs from /v1/lora/installed
 * - Real-time compatibility check against current checkpoint model
 * - Architecture badges (SD1.5 / SDXL / Pony / Flux) per LoRA
 * - Grouped display: Compatible first, then Incompatible
 * - Warning tooltips for incompatible LoRAs
 * - Checkbox toggle per LoRA
 * - Weight slider per LoRA (0.0 – 1.5, default 0.8)
 * - Max 4 LoRA stack limit (VRAM guard)
 * - Cyber-Noir aesthetic matching the Edit page
 */

import React, { useEffect, useState, useMemo, useCallback } from 'react'

export type ActiveLora = {
  id: string
  weight: number
  enabled: boolean
}

type InstalledLora = {
  id: string
  filename: string
  path: string
  enabled: boolean
  weight: number
  base: string         // "sd1.5", "sdxl", "pony", "flux", ""
  base_label: string   // "SD1.5", "SDXL", "Pony", "Flux", ""
  healthy: boolean     // true if file is valid, false if corrupt
  health_error: string // error description if corrupt
  file_size: number    // file size in bytes
  file_size_human: string // "144.2 MB"
  gated: boolean       // true = NSFW, only show when nsfwMode enabled
}

type CompatibilityData = {
  checkpoint: string
  checkpoint_arch: string
  checkpoint_arch_label: string
  loras: Array<InstalledLora & { compatible: boolean | null }>
}

type LoraManagerProps = {
  backendUrl: string
  apiKey?: string
  activeLoras: ActiveLora[]
  onLorasChange: (loras: ActiveLora[]) => void
  disabled?: boolean
  /** Current checkpoint model filename (e.g. "sd_xl_base_1.0.safetensors") */
  currentModel?: string
  /** When false, NSFW/gated LoRAs are hidden from the list */
  nsfwMode?: boolean
}

const MAX_LORA_STACK = 4

export function LoraManager({ backendUrl, apiKey, activeLoras, onLorasChange, disabled, currentModel, nsfwMode }: LoraManagerProps) {
  const [installed, setInstalled] = useState<InstalledLora[]>([])
  const [compatData, setCompatData] = useState<CompatibilityData | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const [hoveredLora, setHoveredLora] = useState<string | null>(null)
  const [deletingLora, setDeletingLora] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const headers = useMemo(
    (): Record<string, string> => (apiKey ? { 'x-api-key': apiKey } : {}),
    [apiKey]
  )
  const base = useMemo(() => backendUrl.replace(/\/+$/, ''), [backendUrl])

  // Fetch installed LoRAs on mount
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch(`${base}/v1/lora/installed`, { headers })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!cancelled) {
          const items: InstalledLora[] = data.loras || []
          setInstalled(items)

          // Initialize activeLoras from installed list (only if empty)
          if (activeLoras.length === 0 && items.length > 0) {
            onLorasChange(
              items.map((l) => ({ id: l.id, weight: 0.8, enabled: false }))
            )
          }
        }
      } catch {
        // Silently degrade — no LoRAs installed
        if (!cancelled) setInstalled([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [backendUrl, apiKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // Filter out gated/NSFW LoRAs when nsfwMode is disabled
  const visibleInstalled = useMemo(
    () => installed.filter((l) => !l.gated || nsfwMode),
    [installed, nsfwMode]
  )

  // Sync activeLoras: remove any gated LoRAs that are now hidden
  useEffect(() => {
    if (!nsfwMode && activeLoras.length > 0) {
      const gatedIds = new Set(installed.filter((l) => l.gated).map((l) => l.id))
      const hasGated = activeLoras.some((l) => gatedIds.has(l.id) && l.enabled)
      if (hasGated) {
        onLorasChange(activeLoras.map((l) =>
          gatedIds.has(l.id) ? { ...l, enabled: false } : l
        ))
      }
    }
  }, [nsfwMode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch compatibility whenever currentModel changes
  useEffect(() => {
    if (!currentModel || installed.length === 0) {
      setCompatData(null)
      return
    }
    let cancelled = false
    const check = async () => {
      try {
        const res = await fetch(
          `${base}/v1/lora/compatibility?checkpoint=${encodeURIComponent(currentModel)}`,
          { headers }
        )
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data: CompatibilityData = await res.json()
        if (!cancelled) setCompatData(data)
      } catch {
        if (!cancelled) setCompatData(null)
      }
    }
    check()
    return () => { cancelled = true }
  }, [currentModel, installed.length, base, headers])

  // Build a compatibility lookup map: lora id → compatible (true/false/null)
  const compatMap = useMemo(() => {
    const map = new Map<string, boolean | null>()
    if (compatData?.loras) {
      for (const l of compatData.loras) {
        map.set(l.id, l.compatible)
      }
    }
    return map
  }, [compatData])

  // Build installed lookup: lora id → InstalledLora (with base info)
  const installedMap = useMemo(() => {
    const map = new Map<string, InstalledLora>()
    for (const l of visibleInstalled) {
      map.set(l.id, l)
    }
    return map
  }, [visibleInstalled])

  // Group and sort LoRAs: compatible first, then unknown, then incompatible
  const sortedLoras = useMemo(() => {
    if (!activeLoras.length) return []
    return [...activeLoras].sort((a, b) => {
      const ca = compatMap.get(a.id)
      const cb = compatMap.get(b.id)
      const order = (v: boolean | null | undefined) =>
        v === true ? 0 : v === null || v === undefined ? 1 : 2
      return order(ca) - order(cb)
    })
  }, [activeLoras, compatMap])

  // Count by group
  const groupCounts = useMemo(() => {
    let compatible = 0, incompatible = 0, unknown = 0
    for (const lora of activeLoras) {
      const c = compatMap.get(lora.id)
      if (c === true) compatible++
      else if (c === false) incompatible++
      else unknown++
    }
    return { compatible, incompatible, unknown }
  }, [activeLoras, compatMap])

  const enabledCount = activeLoras.filter((l) => l.enabled).length

  const toggleLora = useCallback((id: string) => {
    const updated = activeLoras.map((l) => {
      if (l.id !== id) return l
      // Guard: don't enable if at max
      if (!l.enabled && enabledCount >= MAX_LORA_STACK) return l
      return { ...l, enabled: !l.enabled }
    })
    onLorasChange(updated)
  }, [activeLoras, enabledCount, onLorasChange])

  const updateWeight = useCallback((id: string, weight: number) => {
    const updated = activeLoras.map((l) =>
      l.id === id ? { ...l, weight } : l
    )
    onLorasChange(updated)
  }, [activeLoras, onLorasChange])

  // Reload installed LoRAs (after delete)
  const reloadInstalled = useCallback(async () => {
    try {
      const res = await fetch(`${base}/v1/lora/installed`, { headers })
      if (!res.ok) return
      const data = await res.json()
      const items: InstalledLora[] = data.loras || []
      setInstalled(items)
      // Remove deleted LoRAs from active list
      const ids = new Set(items.map((l) => l.id))
      onLorasChange(activeLoras.filter((l) => ids.has(l.id)))
    } catch { /* ignore */ }
  }, [base, headers, activeLoras, onLorasChange])

  // Delete a corrupt/unwanted LoRA file
  const deleteLora = useCallback(async (id: string) => {
    setDeletingLora(id)
    setDeleteConfirm(null)
    try {
      const res = await fetch(`${base}/v1/lora/${id}`, { method: 'DELETE', headers })
      const data = await res.json()
      if (data.ok) {
        // Refresh list after deletion
        setTimeout(() => reloadInstalled(), 300)
      }
    } catch { /* ignore */ } finally {
      setDeletingLora(null)
    }
  }, [base, headers, reloadInstalled])

  // Count corrupt files (must be before any early return to respect Rules of Hooks)
  const corruptCount = visibleInstalled.filter((l) => l.healthy === false).length
  const corruptIds = useMemo(
    () => new Set(visibleInstalled.filter((l) => l.healthy === false).map((l) => l.id)),
    [visibleInstalled]
  )

  const hasIncompatibleEnabled = activeLoras.some(
    (l) => l.enabled && compatMap.get(l.id) === false
  )
  const hasCorruptEnabled = activeLoras.some(
    (l) => l.enabled && corruptIds.has(l.id)
  )

  if (loading || visibleInstalled.length === 0) return null

  return (
    <div className="space-y-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center justify-between p-3 rounded-xl border transition-colors ${
          hasIncompatibleEnabled
            ? 'bg-amber-500/20 border-amber-500/40 text-amber-300'
            : enabledCount > 0
              ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
              : 'bg-white/5 border-white/10 text-white/60 hover:border-white/20'
        }`}
        disabled={disabled}
      >
        <span className="flex items-center gap-2 font-medium text-sm">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v18" />
            <path d="M3 12h18" />
            <rect x="7" y="7" width="10" height="10" rx="2" />
          </svg>
          LoRA Add-ons
          {enabledCount > 0 && (
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
              hasIncompatibleEnabled ? 'bg-amber-500/30' : 'bg-cyan-500/30'
            }`}>
              {enabledCount}/{MAX_LORA_STACK}
            </span>
          )}
          {hasCorruptEnabled && (
            <span className="text-[10px] text-red-400 font-normal">
              corrupt file
            </span>
          )}
          {hasIncompatibleEnabled && !hasCorruptEnabled && (
            <span className="text-[10px] text-amber-400 font-normal">
              compat issue
            </span>
          )}
        </span>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`transition-transform ${expanded ? 'rotate-90' : ''}`}
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>

      {expanded && (
        <div className="space-y-2 animate-in fade-in slide-in-from-top-2 duration-200">
          {/* Current model indicator */}
          {compatData && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06]">
              <span className="text-[10px] text-white/40 uppercase tracking-wider">Model</span>
              <span className="text-[10px] text-white/70 font-mono truncate">
                {compatData.checkpoint_arch_label || compatData.checkpoint || 'Unknown'}
              </span>
              {groupCounts.compatible > 0 && (
                <span className="text-[10px] text-emerald-400/80 ml-auto">
                  {groupCounts.compatible} compatible
                </span>
              )}
              {groupCounts.incompatible > 0 && (
                <span className="text-[10px] text-amber-400/80">
                  {groupCounts.incompatible} incompatible
                </span>
              )}
              {corruptCount > 0 && (
                <span className="text-[10px] text-red-400/80">
                  {corruptCount} corrupt
                </span>
              )}
            </div>
          )}

          {sortedLoras.map((lora) => {
            const compat = compatMap.get(lora.id)
            const info = installedMap.get(lora.id)
            const baseLabel = info?.base_label || ''
            const isCorrupt = corruptIds.has(lora.id)
            const healthError = info?.health_error || ''
            const fileSize = info?.file_size_human || ''
            const isIncompat = compat === false
            const isCompat = compat === true
            const isHovered = hoveredLora === lora.id
            const isDeleting = deletingLora === lora.id
            const isConfirming = deleteConfirm === lora.id

            return (
              <div
                key={lora.id}
                className={`rounded-xl border p-3 transition-all relative ${
                  isCorrupt
                    ? 'border-red-500/40 bg-red-500/5'
                    : isIncompat && lora.enabled
                      ? 'border-amber-500/40 bg-amber-500/5'
                      : lora.enabled
                        ? 'border-cyan-500/30 bg-cyan-500/5'
                        : isIncompat
                          ? 'border-white/10 bg-white/[0.01] opacity-60'
                          : 'border-white/10 bg-white/[0.02]'
                }`}
                onMouseEnter={() => setHoveredLora(lora.id)}
                onMouseLeave={() => setHoveredLora(null)}
              >
                <div className="flex items-center justify-between mb-1">
                  <label className="flex items-center gap-2 cursor-pointer flex-1 min-w-0">
                    <input
                      type="checkbox"
                      checked={lora.enabled}
                      onChange={() => toggleLora(lora.id)}
                      disabled={disabled || isCorrupt || (!lora.enabled && enabledCount >= MAX_LORA_STACK)}
                      className="w-4 h-4 rounded border-white/20 bg-white/10 text-cyan-500 focus:ring-cyan-500/30 cursor-pointer"
                    />
                    <span className={`text-xs font-medium truncate ${
                      isCorrupt ? 'text-red-400 line-through' : lora.enabled ? 'text-white' : 'text-white/50'
                    }`}>
                      {lora.id}
                    </span>
                  </label>

                  {/* Architecture badge + compatibility icon + file size */}
                  <div className="flex items-center gap-1.5 ml-2 shrink-0">
                    {/* Corrupt badge */}
                    {isCorrupt && (
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wide uppercase bg-red-500/20 text-red-400 border border-red-500/30">
                        CORRUPT
                      </span>
                    )}
                    {/* File size */}
                    {fileSize && !isCorrupt && (
                      <span className="text-[9px] text-white/25 font-mono">{fileSize}</span>
                    )}
                    {baseLabel && !isCorrupt && (
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wide uppercase ${
                        isCompat
                          ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                          : isIncompat
                            ? 'bg-amber-500/15 text-amber-400/80 border border-amber-500/20'
                            : 'bg-white/10 text-white/40 border border-white/10'
                      }`}>
                        {baseLabel}
                      </span>
                    )}
                    {isCompat && !isCorrupt && (
                      <span className="text-emerald-400" title="Compatible with current model">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      </span>
                    )}
                    {isIncompat && !isCorrupt && (
                      <span className="text-amber-400" title={`Incompatible — this LoRA requires ${baseLabel} models`}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                          <line x1="12" y1="9" x2="12" y2="13" />
                          <line x1="12" y1="17" x2="12.01" y2="17" />
                        </svg>
                      </span>
                    )}
                    {lora.enabled && !isCorrupt && (
                      <span className="text-[10px] text-cyan-300/70 font-mono">
                        {lora.weight.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>

                {/* Corrupt file warning + delete action */}
                {isCorrupt && (
                  <div className="mt-1.5 space-y-1.5">
                    <div className="text-[10px] text-red-400/90 flex items-center gap-1">
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="15" y1="9" x2="9" y2="15" />
                        <line x1="9" y1="9" x2="15" y2="15" />
                      </svg>
                      {healthError || 'File is corrupt or incomplete'}
                      {fileSize && <span className="text-white/25 ml-1">({fileSize})</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      {isConfirming ? (
                        <>
                          <button
                            type="button"
                            onClick={() => deleteLora(lora.id)}
                            disabled={isDeleting}
                            className="px-2.5 py-1 rounded-lg bg-red-600 hover:bg-red-500 text-[10px] font-bold text-white transition-all"
                          >
                            {isDeleting ? 'Deleting...' : 'Confirm Delete'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleteConfirm(null)}
                            className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-[10px] text-white/50 transition-all"
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setDeleteConfirm(lora.id)}
                          className="px-2.5 py-1 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/40 text-[10px] font-medium text-red-400 flex items-center gap-1 transition-all"
                        >
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                          </svg>
                          Delete &amp; Re-download
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Incompatibility warning tooltip on hover */}
                {!isCorrupt && isIncompat && isHovered && compatData && (
                  <div className="text-[10px] text-amber-400/90 mt-1 flex items-center gap-1">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" />
                      <line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    This LoRA requires {baseLabel} models. Current model: {compatData.checkpoint_arch_label}
                  </div>
                )}

                {/* Enabled + incompatible: permanent warning */}
                {!isCorrupt && isIncompat && lora.enabled && !isHovered && compatData && (
                  <div className="text-[10px] text-amber-400/80 mt-1">
                    Will be skipped — requires {baseLabel}, current model is {compatData.checkpoint_arch_label}
                  </div>
                )}

                {lora.enabled && !isCorrupt && (
                  <input
                    type="range"
                    min={0}
                    max={1.5}
                    step={0.05}
                    value={lora.weight}
                    onChange={(e) => updateWeight(lora.id, parseFloat(e.target.value))}
                    disabled={disabled}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer mt-1 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:rounded-full"
                  />
                )}
                {lora.weight > 1.2 && lora.enabled && !isCorrupt && (
                  <div className="text-[10px] text-amber-400/70 mt-1">
                    Weight above 1.2 may cause artifacts
                  </div>
                )}
              </div>
            )
          })}

          {enabledCount >= MAX_LORA_STACK && (
            <div className="text-[10px] text-amber-400/60 text-center py-1">
              Max {MAX_LORA_STACK} LoRAs for VRAM safety (12 GB GPUs)
            </div>
          )}
        </div>
      )}
    </div>
  )
}
