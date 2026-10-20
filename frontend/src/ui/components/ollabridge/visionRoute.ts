/**
 * Multimodal (vision) routing for OllaBridge selections — the counterpart of chatRoute.ts.
 *
 * Picking a model on an OllaBridge card in Models → Multimodal points image analysis at that
 * connection, never chat:
 *
 *   provider=openai_compat, base_url=<gateway>/v1 (Local) or <cloud>/ollama/v1 (Cloud), model=<id>
 *
 * Stored under the multimodal keys App.tsx already reads (`homepilot_*_multimodal`) and
 * announced on `homepilot:use-vision-model`, which App.tsx applies to its live settings — the
 * same shape as `homepilot:use-gpu-node` for chat. A model is only routed here after it passed
 * the vision check (visionCheck.ts), or the user chose to use it anyway.
 */
import type { ChatSelection } from './chatRoute'

export const LS_PROVIDER_VISION = 'homepilot_provider_multimodal'
export const LS_MODEL_VISION = 'homepilot_model_multimodal'
export const LS_BASE_URL_VISION = 'homepilot_base_url_multimodal'
export const USE_VISION_MODEL_EVENT = 'homepilot:use-vision-model'

export function readVisionSelection(): ChatSelection {
  try {
    return {
      provider: localStorage.getItem(LS_PROVIDER_VISION) || '',
      model: localStorage.getItem(LS_MODEL_VISION) || '',
      baseUrl: localStorage.getItem(LS_BASE_URL_VISION) || '',
    }
  } catch {
    return { provider: '', model: '', baseUrl: '' }
  }
}

export function routeVisionTo(baseUrl: string, model: string): void {
  try {
    localStorage.setItem(LS_PROVIDER_VISION, 'openai_compat')
    localStorage.setItem(LS_BASE_URL_VISION, baseUrl)
    localStorage.setItem(LS_MODEL_VISION, model)
  } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(USE_VISION_MODEL_EVENT, { detail: { provider: 'openai_compat', baseUrl, model } }))
}
