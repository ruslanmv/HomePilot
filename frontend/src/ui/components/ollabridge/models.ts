/**
 * OllaBridge model normalization — pure helpers shared by the Local and Cloud
 * cards on Model Management → Chat (and by the per-type OllaBridge list).
 *
 * Local gateway (`GET <root>/v1/models`): OpenAI list entries
 *   { id, object, owned_by, source, source_display_name }
 * where `source` is one of ollama | homepilot | relay | direct_endpoint |
 * open_webui | byok:<name> (ollabridge api/main.py `_stamp_model_source`).
 *
 * Cloud (`GET <cloud>/ollama/v1/models`): entries carry `x_source` (legacy
 * `source`) = shared_device | route_alias | cloud_catalog | homepilot, plus
 * `device_id` / `owned_by: "relay:<device>"` for shared models
 * (ollabridge docs/UX_MODEL_VISIBILITY.md).
 */

export type ModelKind = 'chat' | 'multimodal' | 'image' | 'video' | 'enhance' | 'LoRA'

/** Loose model-type guess from the model id — drives badges + per-tab filter. */
export function guessModelType(id: string): ModelKind {
  const s = id.toLowerCase()
  if (/(llava|vision|-vl|minicpm-v|moondream)/.test(s)) return 'multimodal'
  if (/(sdxl|flux|stable-diffusion|sd15|sd3|pony|dreamshaper)/.test(s)) return 'image'
  if (/(svd|ltx|wan|video)/.test(s)) return 'video'
  if (/(upscal|esrgan|enhance|restore|gfpgan|codeformer)/.test(s)) return 'enhance'
  if (/lora/.test(s)) return 'LoRA'
  return 'chat'
}

/** Can this model answer a chat completion? (text or vision chat, not embeddings) */
export function isChatCapable(id: string): boolean {
  if (/embed/i.test(id)) return false
  const kind = guessModelType(id)
  return kind === 'chat' || kind === 'multimodal'
}

/** `deepseek-r1:latest` → `deepseek-r1`; every other id is shown as is. */
export function displayModelId(id: string): string {
  return id.replace(/:latest$/i, '')
}

function titleCase(s: string): string {
  return s
    .split(/[-_:\s]+/)
    .filter(Boolean)
    .map((w) => (w.toLowerCase() === 'ollabridge' ? 'OllaBridge' : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ')
}

function hostOf(url: string): string {
  try { return new URL(url).host } catch { return url }
}

// ── Local gateway ────────────────────────────────────────────────────────────

/**
 * What a gateway entry is, in the gateway's own words — never guessed from the id:
 * `model` is a base model; `assistant` is a preset or workflow built on one (OllaBridge
 * marks Open WebUI presets `preset: true` / `category: "preset_or_workflow"`).
 */
export type GatewayModelKind = 'model' | 'assistant'

export interface GatewayModel {
  id: string
  /** Where the gateway serves it from, e.g. "Ollama", "HomePilot", "Relay node". */
  origin: string
  /** Dropdown text, e.g. "deepseek-r1 (Ollama)". */
  label: string
  kind: GatewayModelKind
  /** The gateway's display name, when it has one ("Natro Destek Koçu"). */
  name?: string
  /** The gateway hides it, or reports it stale / not available. */
  hidden?: boolean
  available?: boolean
}

function kindOf(entry: Record<string, unknown>): GatewayModelKind {
  if (entry.preset === true) return 'assistant'
  const category = String(entry.category || '').toLowerCase()
  if (category && category !== 'chat' && /preset|workflow|assistant|agent|pipe/.test(category)) return 'assistant'
  return 'model'
}

/**
 * The gateway's own suggestion for a model list: base models that are available and not
 * hidden. Assistants stay reachable through "Choose models" — they are just not the default.
 */
export function suggestedByGateway(m: GatewayModel): boolean {
  return m.kind === 'model' && !m.hidden && m.available !== false
}

const KNOWN_OWNERS: Record<string, string> = {
  ollama: 'Ollama',
  homepilot: 'HomePilot',
  relay: 'Relay node',
  direct_endpoint: 'Direct endpoint',
  open_webui: 'Open WebUI',
  openwebui: 'Open WebUI',
}

/** Human origin for one gateway `/v1/models` entry. */
export function localOriginLabel(entry: Record<string, unknown>): string {
  const source = String(entry.source || '').trim()
  const display = String(entry.source_display_name || '').trim()
  const lower = source.toLowerCase()
  if (lower === 'ollama') return 'Ollama'
  if (lower === 'homepilot') return 'HomePilot'
  // "Relay node <long id>" is noise in a dropdown; the id lives in the dashboard.
  if (lower === 'relay') return 'Relay node'
  if (lower === 'direct_endpoint') return display ? hostOf(display) : 'Direct endpoint'
  if (lower === 'open_webui') return display || 'Open WebUI'
  if (lower.startsWith('byok:')) return display || titleCase(source.slice(5))
  if (display) return display
  if (source) return KNOWN_OWNERS[lower] || source
  const owner = String(entry.owned_by || '').trim()
  if (owner) return KNOWN_OWNERS[owner.toLowerCase()] || owner
  return 'OllaBridge'
}

/**
 * Normalize a gateway `/v1/models` body (or a bare id list) into chat-capable
 * dropdown options. Duplicate ids served by several origins are merged — the
 * gateway routes by id, so one option per id.
 */
export function normalizeLocalModels(payload: unknown): GatewayModel[] {
  const data: unknown[] = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { data?: unknown }).data)
      ? ((payload as { data: unknown[] }).data)
      : []
  const byId = new Map<string, { origins: string[]; entry: Record<string, unknown> }>()
  for (const raw of data) {
    const entry: Record<string, unknown> | null =
      typeof raw === 'string' ? { id: raw } : raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
    if (!entry) continue
    const id = String(entry.id || '').trim()
    if (!id || !isChatCapable(id)) continue
    // The gateway says when a model cannot chat; believe it over the id.
    const caps = entry.capabilities as Record<string, unknown> | undefined
    if (caps && caps.chat === false) continue
    const origin = localOriginLabel(entry)
    const known = byId.get(id)
    if (!known) byId.set(id, { origins: [origin], entry })
    else if (!known.origins.includes(origin)) known.origins.push(origin)
  }
  return [...byId.entries()].map(([id, { origins, entry }]) => {
    const origin = origins.join(', ')
    const kind = kindOf(entry)
    const name = typeof entry.name === 'string' && entry.name.trim() ? entry.name.trim() : undefined
    const status = String(entry.status || '').toLowerCase()
    // An assistant's id is a slug ("natro-destek-kou"); its name is what people recognise.
    // A model id that repeats its source ("openwebui/internal-gemma4-31b" from Open WebUI)
    // is shown without the prefix the origin already names. The id sent to chat never changes.
    const owner = String(entry.owned_by || '').trim().toLowerCase()
    let shown = kind === 'assistant' && name ? name : displayModelId(id)
    if (owner && shown.toLowerCase().startsWith(`${owner}/`)) shown = shown.slice(owner.length + 1)
    return {
      id,
      origin,
      label: `${shown} (${origin})`,
      kind,
      ...(name ? { name } : {}),
      hidden: entry.hidden === true,
      available: entry.stale !== true && (!status || status === 'available'),
    }
  })
}

// ── Cloud ────────────────────────────────────────────────────────────────────

export interface CloudDevice {
  id: string
  name: string
  platform?: string | null
  online: boolean
  gpu_name?: string | null
  vram_mb?: number | null
}

export interface CloudModel {
  id: string
  owned_by?: string
  source?: string
  x_source?: string
  device_id?: string
  device_name?: string
  name?: string
  display_name?: string
}

export type CloudGroup = 'shared' | 'route' | 'catalog' | 'persona' | 'other'

export const CLOUD_GROUP_ORDER: CloudGroup[] = ['shared', 'route', 'catalog', 'persona', 'other']

export const CLOUD_GROUP_LABEL: Record<CloudGroup, string> = {
  shared: 'My shared models',
  route: 'Cloud routes',
  catalog: 'Cloud catalog',
  persona: 'HomePilot personas',
  other: 'Other cloud models',
}

export interface CloudModelOption {
  id: string
  label: string
  group: CloudGroup
  /** False for models whose only device is offline — shown, never selectable. */
  available: boolean
}

export function cloudSourceOf(m: CloudModel): string {
  return String(m.x_source || m.source || '').trim().toLowerCase()
}

function deviceIdOf(m: CloudModel): string {
  if (m.device_id) return String(m.device_id)
  const match = /^relay:([A-Za-z0-9._:-]{1,128})$/.exec(String(m.owned_by || ''))
  return match ? match[1] : ''
}

function groupOf(source: string): CloudGroup {
  if (source === 'shared_device') return 'shared'
  if (source === 'route_alias') return 'route'
  if (source === 'cloud_catalog') return 'catalog'
  if (source === 'homepilot') return 'persona'
  return 'other'
}

/**
 * Normalize the Cloud model list (plus the device list for names and online
 * state) into grouped dropdown options: own shared models first, then smart
 * routes, then catalog / persona / other entries the Cloud chose to expose.
 * A shared model is available only while at least one of its devices is
 * online; one served by offline devices only is kept but marked unavailable.
 */
export function normalizeCloudModels(models: CloudModel[], devices: CloudDevice[] = []): CloudModelOption[] {
  const deviceById = new Map(devices.map((d) => [String(d.id), d]))
  type Acc = { id: string; group: CloudGroup; names: string[]; available: boolean; base: string; owner: string }
  const byId = new Map<string, Acc>()
  for (const m of Array.isArray(models) ? models : []) {
    if (!m || typeof m !== 'object') continue
    const id = String(m.id || '').trim()
    if (!id || !isChatCapable(id)) continue
    const group = groupOf(cloudSourceOf(m))
    let available = true
    let deviceName = ''
    let base = displayModelId(id)
    if (group === 'shared') {
      const dev = deviceById.get(deviceIdOf(m))
      deviceName = dev?.name || m.device_name || ''
      available = dev ? dev.online !== false : true
    } else if (group === 'route') {
      base = m.display_name || m.name || titleCase(id)
    } else if (group === 'persona') {
      base = m.display_name || m.name || id
    }
    const owner = String(m.owned_by || '').trim()
    const prev = byId.get(id)
    if (!prev) {
      byId.set(id, { id, group, names: deviceName ? [deviceName] : [], available, base, owner })
      continue
    }
    if (prev.group === 'shared' && group === 'shared') {
      if (deviceName && !prev.names.includes(deviceName)) prev.names.push(deviceName)
      prev.available = prev.available || available
    } else if (!prev.available && available) {
      byId.set(id, { id, group, names: deviceName ? [deviceName] : [], available, base, owner })
    }
  }
  const out: CloudModelOption[] = []
  for (const acc of byId.values()) {
    let suffix: string
    if (acc.group === 'shared') suffix = acc.names.length ? acc.names.join(', ') : 'your device'
    else if (acc.group === 'route') suffix = 'Cloud route'
    else if (acc.group === 'catalog') suffix = 'Cloud'
    else if (acc.group === 'persona') suffix = 'HomePilot persona'
    else suffix = acc.owner && !acc.owner.startsWith('relay:') ? acc.owner : 'Cloud'
    out.push({
      id: acc.id,
      group: acc.group,
      available: acc.available,
      label: `${acc.base} (${suffix})${acc.available ? '' : ' — offline'}`,
    })
  }
  return out.sort((a, b) => CLOUD_GROUP_ORDER.indexOf(a.group) - CLOUD_GROUP_ORDER.indexOf(b.group))
}
