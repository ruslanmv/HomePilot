/**
 * TTS plugin registry.
 *
 * Providers call ``register(provider)`` from their own module at import
 * time. The active engine is persisted in localStorage under a
 * user-scoped key so account switches don't leak engine choice.
 *
 * Subscriptions (``onActiveChange``) let React re-render when the user
 * picks a new engine.
 */

import {
  registerUserScopedKey,
  userScopedKey,
  getCurrentUserId,
} from '../../lib/userScopedStorage'
import type { TtsEngineId, TtsProvider } from './types'

const ACTIVE_ENGINE_BASE_KEY = 'homepilot_tts_engine'
const DEFAULT_ENGINE_ID = 'web-speech-api'

// Scope the active-engine pointer per user so switching accounts keeps
// each user's TTS preference distinct.
registerUserScopedKey(ACTIVE_ENGINE_BASE_KEY)

function _activeStorageKey(): string {
  const uid = getCurrentUserId()
  return uid ? userScopedKey(ACTIVE_ENGINE_BASE_KEY, uid) : ACTIVE_ENGINE_BASE_KEY
}

// ── Registry storage ─────────────────────────────────────────────────────────

const _providers = new Map<TtsEngineId, TtsProvider>()
const _listeners = new Set<(id: TtsEngineId) => void>()

/** Register a provider. Idempotent — later registrations with the same
 *  id overwrite the earlier one (useful for hot-reload during dev). */
export function register(provider: TtsProvider): void {
  _providers.set(provider.id, provider)
}

export function list(): readonly TtsProvider[] {
  return Array.from(_providers.values())
}

export function get(id: TtsEngineId): TtsProvider | undefined {
  return _providers.get(id)
}

/** Return the engine id the user picked (falling back to the default). */
export function getActiveId(): TtsEngineId {
  try {
    const saved =
      localStorage.getItem(_activeStorageKey()) ||
      localStorage.getItem(ACTIVE_ENGINE_BASE_KEY)
    if (saved && _providers.has(saved)) return saved
  } catch {
    // localStorage access can throw in private mode / sandboxed iframes.
  }
  return DEFAULT_ENGINE_ID
}

export function getActive(): TtsProvider | undefined {
  return _providers.get(getActiveId())
}

/** Persist and broadcast a new active engine. No-op if the id is not
 *  registered — callers should list() first to filter. */
export function setActive(id: TtsEngineId): void {
  if (!_providers.has(id)) return
  try {
    localStorage.setItem(_activeStorageKey(), id)
    // Also write the un-scoped base key so the old legacy code path
    // (pre-registry features reading the raw key) sees the same value.
    localStorage.setItem(ACTIVE_ENGINE_BASE_KEY, id)
  } catch {
    // Non-fatal: state still lives in the subscriber's React tree.
  }
  for (const fn of _listeners) {
    try { fn(id) } catch { /* isolate subscribers */ }
  }
}

/** Subscribe to active-engine changes. Returns an unsubscribe fn. */
export function onActiveChange(fn: (id: TtsEngineId) => void): () => void {
  _listeners.add(fn)
  return () => { _listeners.delete(fn) }
}

// ── Per-provider settings (small JSON blob under a scoped key) ───────────────

function _settingsKey(providerId: TtsEngineId): string {
  const base = `homepilot_tts_settings:${providerId}`
  const uid = getCurrentUserId()
  return uid ? userScopedKey(base, uid) : base
}

/** Read the saved settings for a provider as a plain object. Unknown
 *  providers return {}. Callers are expected to merge defaults from
 *  ``getSettingsSchema()``. */
export function readSettings(providerId: TtsEngineId): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(_settingsKey(providerId))
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

/** Overwrite the settings blob for a provider. Merges with whatever
 *  is already there so callers can update one field at a time. */
export function writeSettings(
  providerId: TtsEngineId,
  partial: Record<string, unknown>,
): void {
  try {
    const current = readSettings(providerId)
    const next = { ...current, ...partial }
    localStorage.setItem(_settingsKey(providerId), JSON.stringify(next))
  } catch {
    // Non-fatal.
  }
}
