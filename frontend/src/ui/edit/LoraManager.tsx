/**
 * LoraManager — Lightweight LoRA toggle + weight control for the Edit page.
 *
 * Additive component (Golden Rule 1.0).
 * Does NOT modify any existing Edit tab logic — it just provides state
 * that the parent can read and pass into the edit message flags.
 *
 * Features:
 * - Fetches installed LoRAs from /v1/lora/installed
 * - Checkbox toggle per LoRA
 * - Weight slider per LoRA (0.0 – 1.5, default 0.8)
 * - Max 4 LoRA stack limit (VRAM guard)
 * - Cyber-Noir aesthetic matching the Edit page
 */

import React, { useEffect, useState } from 'react'

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
}

type LoraManagerProps = {
  backendUrl: string
  apiKey?: string
  activeLoras: ActiveLora[]
  onLorasChange: (loras: ActiveLora[]) => void
  disabled?: boolean
}

const MAX_LORA_STACK = 4

export function LoraManager({ backendUrl, apiKey, activeLoras, onLorasChange, disabled }: LoraManagerProps) {
  const [installed, setInstalled] = useState<InstalledLora[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const base = backendUrl.replace(/\/+$/, '')
        const headers: Record<string, string> = apiKey ? { 'x-api-key': apiKey } : {}
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

  if (loading || installed.length === 0) return null

  const enabledCount = activeLoras.filter((l) => l.enabled).length

  const toggleLora = (id: string) => {
    const updated = activeLoras.map((l) => {
      if (l.id !== id) return l
      // Guard: don't enable if at max
      if (!l.enabled && enabledCount >= MAX_LORA_STACK) return l
      return { ...l, enabled: !l.enabled }
    })
    onLorasChange(updated)
  }

  const updateWeight = (id: string, weight: number) => {
    const updated = activeLoras.map((l) =>
      l.id === id ? { ...l, weight } : l
    )
    onLorasChange(updated)
  }

  return (
    <div className="space-y-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center justify-between p-3 rounded-xl border transition-colors ${
          enabledCount > 0
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
            <span className="px-2 py-0.5 rounded-full bg-cyan-500/30 text-[10px] font-bold">
              {enabledCount}/{MAX_LORA_STACK}
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
          {activeLoras.map((lora) => (
            <div
              key={lora.id}
              className={`rounded-xl border p-3 transition-all ${
                lora.enabled
                  ? 'border-cyan-500/30 bg-cyan-500/5'
                  : 'border-white/10 bg-white/[0.02]'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <label className="flex items-center gap-2 cursor-pointer flex-1 min-w-0">
                  <input
                    type="checkbox"
                    checked={lora.enabled}
                    onChange={() => toggleLora(lora.id)}
                    disabled={disabled || (!lora.enabled && enabledCount >= MAX_LORA_STACK)}
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-cyan-500 focus:ring-cyan-500/30 cursor-pointer"
                  />
                  <span className={`text-xs font-medium truncate ${
                    lora.enabled ? 'text-white' : 'text-white/50'
                  }`}>
                    {lora.id}
                  </span>
                </label>
                {lora.enabled && (
                  <span className="text-[10px] text-cyan-300/70 font-mono ml-2 shrink-0">
                    {lora.weight.toFixed(2)}
                  </span>
                )}
              </div>
              {lora.enabled && (
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
              {lora.weight > 1.2 && lora.enabled && (
                <div className="text-[10px] text-amber-400/70 mt-1">
                  Weight above 1.2 may cause artifacts
                </div>
              )}
            </div>
          ))}

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
