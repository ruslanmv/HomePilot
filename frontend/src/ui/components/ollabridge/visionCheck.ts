/**
 * The vision check — does this model really see images through this connection?
 *
 * Names and capability flags are not evidence (a gateway flagged a text-only model as vision,
 * and left real vision models unflagged), and a route that drops the picture still gets a
 * confident answer. So before a model is used for images, HomePilot's backend shows it a known
 * test image (`POST /v1/multimodal/check`, backend/app/vision_check.py) and reports whether it
 * named what was in it. The verdict is remembered per connection + model, so each model is
 * checked once — and a newly added model is checked the moment it is chosen.
 */
import { useCallback, useEffect, useState } from 'react'
import { isSuggested, type ShelfModel } from '../../lib/modelShelf'

export interface VisionVerdict {
  sees: boolean
  /** What the model said, shortened. */
  answer?: string
  /** Why it failed, in words a person can act on. */
  reason?: string
  at: number
}

export const VISION_CHECKS_KEY = 'homepilot_vision_checks_v1'
export const VISION_CHECKS_EVENT = 'homepilot:vision-checks-changed'

type Checks = Record<string, VisionVerdict>

export function checkKey(baseUrl: string, model: string): string {
  return `${(baseUrl || '').trim().replace(/\/+$/, '').toLowerCase()}|${model}`
}

export function readChecks(): Checks {
  try {
    const parsed = JSON.parse(localStorage.getItem(VISION_CHECKS_KEY) || '{}')
    return parsed && typeof parsed === 'object' ? (parsed as Checks) : {}
  } catch {
    return {}
  }
}

function writeCheck(key: string, verdict: VisionVerdict): void {
  const all = readChecks()
  all[key] = verdict
  try {
    localStorage.setItem(VISION_CHECKS_KEY, JSON.stringify(all))
  } catch { /* storage full or blocked: the check simply runs again next time */ }
  window.dispatchEvent(new CustomEvent(VISION_CHECKS_EVENT))
}

export interface CheckTarget {
  backendUrl?: string
  backendApiKey?: string
  baseUrl: string
  model: string
  /** Sent only to HomePilot's backend for this one check, never stored. */
  apiKey?: string
}

/** Run the check through HomePilot's backend and remember the verdict. */
export async function runVisionCheck(t: CheckTarget): Promise<VisionVerdict> {
  const backend = (t.backendUrl || '').replace(/\/+$/, '')
  let verdict: VisionVerdict
  try {
    const r = await fetch(`${backend}/v1/multimodal/check`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(t.backendApiKey ? { 'x-api-key': t.backendApiKey } : {}),
      },
      body: JSON.stringify({
        provider: 'openai_compat',
        base_url: t.baseUrl,
        model: t.model,
        ...(t.apiKey ? { api_key: t.apiKey } : {}),
      }),
    })
    const body = await r.json().catch(() => null)
    if (!r.ok || !body) {
      verdict = { sees: false, reason: `The check could not run (HTTP ${r.status}).`, at: Date.now() }
    } else {
      verdict = {
        sees: body.sees_images === true,
        answer: typeof body.answer === 'string' ? body.answer.slice(0, 200) : undefined,
        reason: typeof body.reason === 'string' && body.reason ? body.reason : undefined,
        at: Date.now(),
      }
    }
  } catch {
    // Not remembered: an unreachable backend says nothing about the model.
    return { sees: false, reason: 'HomePilot’s server could not be reached to run the check.', at: Date.now() }
  }
  writeCheck(checkKey(t.baseUrl, t.model), verdict)
  return verdict
}

/**
 * Multimodal's default list: base models that passed the vision check — or, until a model has
 * been checked, the ones the connection claims can see. A failed check always wins over a claim.
 */
export function visionSuggest(verdictOf: (id: string) => VisionVerdict | undefined) {
  return (m: ShelfModel) => {
    if (!isSuggested(m)) return false
    const verdict = verdictOf(m.id)
    return verdict ? verdict.sees : m.vision === true
  }
}

/** The status shown beside each model on Multimodal. */
export function visionStatus(m: { vision?: boolean }, verdict?: VisionVerdict, checking?: boolean): string {
  if (checking) return 'checking…'
  if (verdict) return verdict.sees ? '✓ sees images' : '✗ no images'
  return m.vision ? 'claims vision · not checked' : 'not checked'
}

/** Remembered verdicts, kept current, plus which checks are running now. */
export function useVisionChecks() {
  const [checks, setChecks] = useState<Checks>(readChecks)
  const [running, setRunning] = useState<Record<string, boolean>>({})
  useEffect(() => {
    const reread = () => setChecks(readChecks())
    const onStorage = (e: StorageEvent) => { if (e.key === VISION_CHECKS_KEY) reread() }
    window.addEventListener(VISION_CHECKS_EVENT, reread)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(VISION_CHECKS_EVENT, reread)
      window.removeEventListener('storage', onStorage)
    }
  }, [])
  const run = useCallback(async (t: CheckTarget) => {
    const key = checkKey(t.baseUrl, t.model)
    setRunning((r) => ({ ...r, [key]: true }))
    try {
      return await runVisionCheck(t)
    } finally {
      setRunning((r) => {
        const next = { ...r }
        delete next[key]
        return next
      })
    }
  }, [])
  return { checks, running, run }
}
