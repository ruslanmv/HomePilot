/**
 * Live progress of a model install, read from GET /models/install/progress while the install
 * request is still running (backend/app/main.py keeps the download script's latest progress
 * line per model). Shared by the Models catalog rows and the suggestions card, so both show the
 * same "Downloading 42% · 2.7 GB of 6.5 GB · 5.8 MB/s".
 */
import { useEffect, useRef, useState } from 'react'

export type InstallProgress = {
  state: 'idle' | 'running' | 'done' | 'failed'
  percent: number | null
  done?: string
  total?: string
  rate?: string | null
  stage?: string
}

export function parseInstallProgress(raw: unknown): InstallProgress | null {
  if (!raw || typeof raw !== 'object') return null
  const v = raw as Record<string, unknown>
  const state = v.state === 'running' || v.state === 'done' || v.state === 'failed' ? v.state : 'idle'
  const percent = typeof v.percent === 'number' && Number.isFinite(v.percent) ? Math.max(0, Math.min(100, Math.round(v.percent))) : null
  return {
    state,
    percent,
    done: typeof v.done === 'string' ? v.done : undefined,
    total: typeof v.total === 'string' ? v.total : undefined,
    rate: typeof v.rate === 'string' ? v.rate : null,
    stage: typeof v.stage === 'string' ? v.stage : undefined,
  }
}

/** "2.48M" → "2.5 MB", "6.46G" → "6.5 GB"; values Ollama already formats pass through. */
function sizeText(value?: string): string {
  if (!value) return ''
  const m = /^([\d.]+)\s?([kKMGTP])?i?B?$/.exec(value.trim())
  if (!m) return value
  const n = Number(m[1])
  const unit = (m[2] || '').toUpperCase()
  return `${n >= 100 ? Math.round(n) : n.toFixed(1)} ${unit ? `${unit}B` : 'B'}`
}

/** One line for a button or a toast. */
export function progressLabel(p: InstallProgress | null): string {
  if (!p || p.state === 'idle') return 'Starting the download…'
  if (p.state === 'done') return 'Installed — finishing up…'
  if (p.state === 'failed') return 'The download stopped.'
  if (p.percent === null) return p.stage ? `${p.stage}…` : 'Preparing the download…'
  const amount = p.done && p.total ? ` · ${sizeText(p.done)} of ${sizeText(p.total)}` : ''
  const rate = p.rate && !p.rate.startsWith('?') ? ` · ${p.rate.replace(/([kKMGT])B\/s/, (_, u) => ` ${u.toUpperCase()}B/s`).replace(/\s+/g, ' ')}` : ''
  return `Downloading ${p.percent}%${amount}${rate}`
}

/** Polls while `modelId` is set (an install is running), once a second. */
export function useInstallProgress(backendUrl: string, apiKey: string | undefined, modelId: string | null): InstallProgress | null {
  const [progress, setProgress] = useState<InstallProgress | null>(null)
  useEffect(() => {
    if (!modelId) {
      setProgress(null)
      return undefined
    }
    let cancelled = false
    const base = (backendUrl || '').replace(/\/+$/, '')
    const tick = async () => {
      try {
        const res = await fetch(`${base}/models/install/progress?model_id=${encodeURIComponent(modelId)}`, {
          headers: apiKey ? { 'x-api-key': apiKey } : undefined,
          credentials: 'include',
        })
        if (!res.ok) return
        const parsed = parseInstallProgress(await res.json())
        if (!cancelled && parsed) setProgress(parsed)
      } catch {
        /* the install request itself reports failure; progress just stops moving */
      }
    }
    void tick()
    const timer = window.setInterval(() => void tick(), 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [backendUrl, apiKey, modelId])
  return progress
}

/** Every install the backend knows of (running, or finished within the hour), by model id. */
export async function fetchInstalls(backendUrl: string, apiKey?: string): Promise<Record<string, InstallProgress>> {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const res = await fetch(`${base}/models/install/progress`, {
    headers: apiKey ? { 'x-api-key': apiKey } : undefined,
    credentials: 'include',
  })
  if (!res.ok) return {}
  const body = (await res.json().catch(() => null)) as { installs?: Record<string, unknown> } | null
  const out: Record<string, InstallProgress> = {}
  for (const [id, raw] of Object.entries(body?.installs || {})) {
    const p = parseInstallProgress(raw)
    if (p) out[id] = p
  }
  return out
}

/**
 * The installs still running on the backend when a page mounts. An install keeps going after
 * the Models page is left — the backend runs it — so coming back (or reloading) must show it
 * again, same button and bar, instead of a page that has forgotten. Read once per mount; the
 * per-model poll above takes over from there.
 */
export function useRunningInstalls(backendUrl: string, apiKey?: string): string[] {
  const [running, setRunning] = useState<string[]>([])
  useEffect(() => {
    let cancelled = false
    fetchInstalls(backendUrl, apiKey)
      .then((all) => {
        if (!cancelled) setRunning(Object.keys(all).filter((id) => all[id].state === 'running'))
      })
      .catch(() => { /* nothing to pick up */ })
    return () => { cancelled = true }
  }, [backendUrl, apiKey])
  return running
}

export type InstallOutcome = 'done' | 'failed' | 'lost'

/**
 * For an install picked up from the backend rather than started on this page — there is no
 * request to await — reports once how it ended: done, failed, or lost (the backend no longer
 * knows it, e.g. it restarted).
 */
export function useInstallOutcome(progress: InstallProgress | null, watching: boolean, onFinished: (outcome: InstallOutcome) => void): void {
  const latest = useRef(onFinished)
  latest.current = onFinished
  const state = progress?.state
  useEffect(() => {
    if (!watching || !state || state === 'running') return
    latest.current(state === 'done' ? 'done' : state === 'failed' ? 'failed' : 'lost')
  }, [watching, state])
}
