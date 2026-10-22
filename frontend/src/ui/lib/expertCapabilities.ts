/**
 * What the connected models can carry — the gate for the "Deep research" mode.
 *
 * Deep research (plan → sub-agents with tools → cited report) needs a high-end model. The
 * backend measures the connection (`POST /v1/expert/capabilities`: Ollama's /api/tags, or a
 * gateway's model list read by name) and says whether the mode is offered. The chat shows
 * the option disabled, with the reason, until a high-end model is connected.
 */
import { createContext } from 'react'

export type ModelProfile = { name: string; params_b: number | null; tier: 'low' | 'medium' | 'high'; tools_likely: boolean; reason: string; rank: number }

export type ExpertCapabilities = {
  connection: string
  tier: 'low' | 'medium' | 'high'
  selected: ModelProfile
  best: ModelProfile | null
  models: ModelProfile[]
  deep_research: { enabled: boolean; reason: string; model: string | null }
}

export type DeepResearchGate = {
  /** null while unknown (not fetched yet, or no Expert on this HomePilot). */
  enabled: boolean | null
  reason: string
  model: string | null
}

export const UNKNOWN_GATE: DeepResearchGate = { enabled: null, reason: 'Checking which models are connected…', model: null }

export const DeepResearchGateContext = createContext<DeepResearchGate>(UNKNOWN_GATE)

export function deepGateFrom(caps: ExpertCapabilities | null | undefined): DeepResearchGate {
  if (!caps || !caps.deep_research) return UNKNOWN_GATE
  return { enabled: Boolean(caps.deep_research.enabled), reason: caps.deep_research.reason || '', model: caps.deep_research.model ?? null }
}

/** The mode menu's line for Deep research: what it does, in the menu's voice. */
export const DEEP_RESEARCH_CAPTION = 'Plan, research and synthesize a report.'

/** The option's state in the mode menu: pickable, or disabled with a one-line reason. The model
 *  is the chat's own (shown in the composer), so the caption does not repeat it. */
export function deepOptionState(gate: DeepResearchGate): { disabled: boolean; description: string } {
  if (gate.enabled === true) {
    return { disabled: false, description: DEEP_RESEARCH_CAPTION }
  }
  if (gate.enabled === false) {
    return { disabled: true, description: gate.reason || 'Needs a high-end model on this connection.' }
  }
  return { disabled: true, description: gate.reason }
}

export type ExpertTargetBody = { provider: string; base_url?: string; model?: string; api_key?: string }

export async function fetchExpertCapabilities(
  backendUrl: string,
  target: ExpertTargetBody,
  headers?: Record<string, string>,
): Promise<ExpertCapabilities | null> {
  try {
    const res = await fetch(`${backendUrl.replace(/\/+$/, '')}/v1/expert/capabilities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(headers || {}) },
      credentials: 'include',
      body: JSON.stringify({ target, model: target.model || undefined }),
    })
    if (!res.ok) return null
    return (await res.json()) as ExpertCapabilities
  } catch {
    return null
  }
}
