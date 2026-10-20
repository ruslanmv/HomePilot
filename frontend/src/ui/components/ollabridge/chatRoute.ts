/**
 * Chat routing for OllaBridge selections.
 *
 * Picking a model on either OllaBridge card points chat at that connection with
 * HomePilot's existing OpenAI-compatible provider and the existing mechanism:
 *
 *   Local  → provider=openai_compat, base_url=<gateway root>/v1, model=<id>
 *   Cloud  → provider=openai_compat, base_url=<cloud>/ollama/v1, model=<id>
 *
 * Both go through the `homepilot:use-gpu-node` event App.tsx already listens to
 * ("Use for Chat"), which updates the live settings and persists the same
 * localStorage keys written here. The base URL is the connection source, so the
 * same model id on both connections still routes to the gateway it was picked
 * on. Credentials are attached at send time by App.tsx: the Cloud token only
 * for `/ollama/v1` URLs, the Local key only for that exact gateway URL.
 */
import { cloudChatBaseUrl, getCloudUrl } from './ollabridgeCloud'
import { loadLocalSettings, localChatBaseUrl } from './ollabridgeLocal'

export const LS_PROVIDER_CHAT = 'homepilot_provider_chat'
export const LS_MODEL_CHAT = 'homepilot_model_chat'
export const LS_BASE_URL_CHAT = 'homepilot_base_url_chat'
export const USE_GPU_NODE_EVENT = 'homepilot:use-gpu-node'

export type ChatRouteSource = 'ollabridge-local' | 'ollabridge-cloud'

export interface ChatSelection {
  provider: string
  model: string
  baseUrl: string
}

export function readChatSelection(): ChatSelection {
  try {
    return {
      provider: localStorage.getItem(LS_PROVIDER_CHAT) || '',
      model: localStorage.getItem(LS_MODEL_CHAT) || '',
      baseUrl: localStorage.getItem(LS_BASE_URL_CHAT) || '',
    }
  } catch {
    return { provider: '', model: '', baseUrl: '' }
  }
}

/** Compare two base URLs ignoring trailing slashes and scheme/host case. */
export function sameBaseUrl(a: string, b: string): boolean {
  const norm = (u: string) => {
    const s = (u || '').trim().replace(/\/+$/, '')
    try {
      const p = new URL(s)
      return `${p.protocol}//${p.host}${p.pathname.replace(/\/+$/, '')}`.toLowerCase()
    } catch {
      return s.toLowerCase()
    }
  }
  return !!a && !!b && norm(a) === norm(b)
}

/** Is chat currently routed to this base URL (via the openai_compat provider)? */
export function isRoutedTo(sel: ChatSelection, baseUrl: string): boolean {
  return sel.provider === 'openai_compat' && sameBaseUrl(sel.baseUrl, baseUrl)
}

/** Route chat to `model` on `baseUrl` and persist it (same keys App.tsx writes). */
export function routeChatTo(source: ChatRouteSource, baseUrl: string, model: string): void {
  try {
    localStorage.setItem(LS_PROVIDER_CHAT, 'openai_compat')
    localStorage.setItem(LS_BASE_URL_CHAT, baseUrl)
    localStorage.setItem(LS_MODEL_CHAT, model)
  } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(USE_GPU_NODE_EVENT, { detail: { baseUrl, model, source } }))
}

/**
 * Does a saved chat route point at one of the user's OllaBridge connections?
 * Model Management uses this to reopen on the OllaBridge provider.
 */
export function isOllaBridgeChatRoute(provider?: string, baseUrl?: string): boolean {
  if (provider !== 'openai_compat' || !baseUrl) return false
  if (sameBaseUrl(baseUrl, cloudChatBaseUrl(getCloudUrl()))) return true
  return sameBaseUrl(baseUrl, localChatBaseUrl(loadLocalSettings().url))
}
