/**
 * The model shelf — which models are offered for chat, and from where.
 *
 * Two levels, never a hardcoded list:
 *
 *   1. **Models** (Model Management → Chat) decides what is *available*. Each connection — an
 *      OllaBridge gateway, the OllaBridge Cloud — records the catalog it last fetched here, and
 *      the user chooses which of those models to offer ("Choose models"). Until they choose,
 *      the connection's own suggestion applies: base models that are available and not hidden,
 *      as the gateway itself describes them (`preset`, `category`, `hidden`, `status`). A new
 *      base model appears by itself; a new assistant waits to be picked.
 *   2. **Chat settings** (the button in a chat) picks one of the offered models for that chat
 *      only, or keeps the default from Models.
 *
 * One store, keyed by connection (`provider|base URL`), so a third connection is another key
 * rather than another code path. Saved on this computer; changes are announced on
 * `homepilot:model-shelf-changed` so an open Chat settings panel updates without a reload.
 */

import { useEffect, useState } from 'react'

export type ShelfModelKind = 'model' | 'assistant'

/**
 * What the list is for. `chat` is what Chat settings offers; `vision` is Models → Multimodal,
 * kept apart so choosing image models never changes the chat list (or the other way round).
 */
export type ShelfRole = 'chat' | 'vision'

export interface ShelfModel {
  id: string
  label: string
  kind: ShelfModelKind
  /** Optional grouping inside one connection (an origin, a cloud group). */
  group?: string
  hidden?: boolean
  available?: boolean
  /** The connection *claims* the model reads images (not proof — see visionCheck.ts). */
  vision?: boolean
}

export type ShelfMode = 'suggested' | 'custom'

export interface ShelfSource {
  key: string
  role: ShelfRole
  /** "OllaBridge Local", "OllaBridge Cloud". */
  title: string
  provider: string
  baseUrl: string
  /** The catalog as last fetched. */
  models: ShelfModel[]
  mode: ShelfMode
  /** The user's explicit choice, used when `mode` is `custom`. */
  shown: string[]
  /** False after a disconnect or sign-out: offered nowhere, but its choice is kept. */
  active: boolean
  updatedAt: number
}

export const MODEL_SHELF_KEY = 'homepilot_model_shelf_v1'
export const MODEL_SHELF_EVENT = 'homepilot:model-shelf-changed'
/** A catalog bigger than this is cut, so one runaway gateway cannot fill localStorage. */
const MAX_MODELS = 2000

type Shelf = Record<string, ShelfSource>

export function sourceKey(provider: string, baseUrl: string, role: ShelfRole = 'chat'): string {
  const key = `${(provider || '').trim().toLowerCase()}|${(baseUrl || '').trim().replace(/\/+$/, '').toLowerCase()}`
  return role === 'chat' ? key : `${role}:${key}`
}

function storage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

function sanitizeModel(raw: unknown): ShelfModel | null {
  if (!raw || typeof raw !== 'object') return null
  const m = raw as Record<string, unknown>
  const id = typeof m.id === 'string' ? m.id.trim() : ''
  if (!id) return null
  return {
    id,
    label: typeof m.label === 'string' && m.label.trim() ? m.label : id,
    kind: m.kind === 'assistant' ? 'assistant' : 'model',
    ...(typeof m.group === 'string' && m.group ? { group: m.group } : {}),
    ...(m.hidden === true ? { hidden: true } : {}),
    ...(m.available === false ? { available: false } : {}),
    ...(m.vision === true ? { vision: true } : {}),
  }
}

function sanitizeSource(key: string, raw: unknown): ShelfSource | null {
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  const models = Array.isArray(s.models)
    ? (s.models.map(sanitizeModel).filter(Boolean) as ShelfModel[]).slice(0, MAX_MODELS)
    : []
  return {
    key,
    role: s.role === 'vision' ? 'vision' : 'chat',
    title: typeof s.title === 'string' ? s.title : key,
    provider: typeof s.provider === 'string' ? s.provider : '',
    baseUrl: typeof s.baseUrl === 'string' ? s.baseUrl : '',
    models,
    mode: s.mode === 'custom' ? 'custom' : 'suggested',
    shown: Array.isArray(s.shown) ? s.shown.filter((x): x is string => typeof x === 'string').slice(0, MAX_MODELS) : [],
    active: s.active !== false,
    updatedAt: typeof s.updatedAt === 'number' ? s.updatedAt : 0,
  }
}

export function readShelf(): Shelf {
  try {
    const raw = storage()?.getItem(MODEL_SHELF_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    const out: Shelf = {}
    if (parsed && typeof parsed === 'object') {
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        const source = sanitizeSource(key, value)
        if (source) out[key] = source
      }
    }
    return out
  } catch {
    return {}
  }
}

function writeShelf(shelf: Shelf): void {
  try {
    storage()?.setItem(MODEL_SHELF_KEY, JSON.stringify(shelf))
  } catch {
    /* full or blocked storage: the shelf simply is not remembered */
  }
  try {
    window.dispatchEvent(new CustomEvent(MODEL_SHELF_EVENT))
  } catch {
    /* no window */
  }
}

export function getSource(key: string): ShelfSource | null {
  return readShelf()[key] || null
}

/** Level 1: record what a connection offers now. The user's choice of what to show is kept. */
export function rememberCatalog(
  info: { title: string; provider: string; baseUrl: string; role?: ShelfRole },
  models: ShelfModel[],
): ShelfSource {
  const shelf = readShelf()
  const role: ShelfRole = info.role ?? 'chat'
  const key = sourceKey(info.provider, info.baseUrl, role)
  const previous = shelf[key]
  const next: ShelfSource = {
    key,
    role,
    title: info.title,
    provider: info.provider,
    baseUrl: info.baseUrl,
    models: models.map(sanitizeModel).filter(Boolean).slice(0, MAX_MODELS) as ShelfModel[],
    mode: previous?.mode ?? 'suggested',
    shown: previous?.shown ?? [],
    active: true,
    updatedAt: Date.now(),
  }
  shelf[key] = next
  writeShelf(shelf)
  return next
}

/** Level 1: the user chose what to offer. `suggested` goes back to the connection's own default. */
export function setShown(key: string, mode: ShelfMode, shown: string[] = []): void {
  const shelf = readShelf()
  const source = shelf[key]
  if (!source) return
  shelf[key] = { ...source, mode, shown: mode === 'custom' ? [...new Set(shown)] : [] }
  writeShelf(shelf)
}

/** A connection went away (disconnect, sign-out): stop offering it, keep what the user chose. */
export function deactivateSource(key: string): void {
  const shelf = readShelf()
  if (!shelf[key] || !shelf[key].active) return
  shelf[key] = { ...shelf[key], active: false }
  writeShelf(shelf)
}

export function isSuggested(m: ShelfModel): boolean {
  return m.kind === 'model' && !m.hidden && m.available !== false
}

/**
 * The models a connection offers, in catalog order. ``suggest`` replaces the default rule for
 * the suggested list — Multimodal passes one that also asks the vision check.
 */
export function shownModels(
  source: ShelfSource | null | undefined,
  suggest: (m: ShelfModel) => boolean = isSuggested,
): ShelfModel[] {
  if (!source) return []
  if (source.mode === 'custom') {
    const wanted = new Set(source.shown)
    return source.models.filter((m) => wanted.has(m.id))
  }
  return source.models.filter(suggest)
}

/** Level 2: every connection's offered models, for a chat to choose from. */
export function chatChoices(shelf: Shelf = readShelf()): Array<{ source: ShelfSource; models: ShelfModel[] }> {
  return Object.values(shelf)
    .filter((source) => source.active && source.role === 'chat')
    .map((source) => ({ source, models: shownModels(source) }))
    .filter((group) => group.models.length > 0)
    .sort((a, b) => a.source.title.localeCompare(b.source.title))
}

export function subscribeShelf(listener: () => void): () => void {
  const onStorage = (e: StorageEvent) => { if (e.key === MODEL_SHELF_KEY) listener() }
  window.addEventListener(MODEL_SHELF_EVENT, listener)
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(MODEL_SHELF_EVENT, listener)
    window.removeEventListener('storage', onStorage)
  }
}

/** The shelf, kept current while the component is mounted. */
export function useModelShelf(): Shelf {
  const [shelf, setShelf] = useState<Shelf>(readShelf)
  useEffect(() => subscribeShelf(() => setShelf(readShelf())), [])
  return shelf
}
