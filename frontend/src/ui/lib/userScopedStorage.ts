/**
 * userScopedStorage — per-user localStorage namespacing.
 *
 * Industry best-practice for multi-account SaaS clients (mirrors the pattern
 * used by ChatGPT, Claude Enterprise, and other production multi-tenant UIs):
 * client-side UI state MUST be namespaced per authenticated user so that
 * switching accounts never leaks the previous user's context into the new
 * session. This module provides the minimum primitives to enforce that.
 *
 * Design
 * ------
 *  - Feature modules (Chat, Projects, Imagine, Gallery, …) register a
 *    localStorage base key once, at module load.
 *  - AuthGate orchestrates the lifecycle:
 *      on login           → restoreActiveStateForUser(user.id)
 *      on account switch  → persistActiveStateForUser(prev.id)
 *                           then restoreActiveStateForUser(next.id)
 *      on logout          → persistActiveStateForUser(user.id)
 *                           then clearActiveUiState()
 *
 * Physical layout in localStorage
 * -------------------------------
 *   <baseKey>                    → current-session pointer (read by the UI)
 *   <baseKey>:user:<userId>      → per-user saved copy
 *
 *  The UI reads/writes the un-suffixed base key as before. Scoping happens
 *  only at login / logout / account-switch boundaries, so feature code does
 *  not need to thread a userId through every call site.
 *
 * Call-site helpers
 * -----------------
 *   userScopedKey(base, userId)   — compose a scoped key (for features that
 *                                   want to address scoped storage directly,
 *                                   e.g. hydrating state on mount).
 *   getCurrentUserId()            — resolve the active user id from the
 *                                   persisted auth blob. Returns '' if
 *                                   unauthenticated.
 */

const USER_KEY_PREFIX = ':user:'
const AUTH_USER_LS_KEY = 'homepilot_auth_user'

const registry = new Set<string>()

/** Feature modules call this at module load to opt their key into per-user
 *  scoping. Idempotent. */
export function registerUserScopedKey(baseKey: string): void {
  if (baseKey) registry.add(baseKey)
}

/** Inspect the current registry (primarily for tests / debugging). */
export function registeredUserScopedKeys(): readonly string[] {
  return Array.from(registry)
}

/** Compose the per-user scoped key. */
export function userScopedKey(baseKey: string, userId: string): string {
  return `${baseKey}${USER_KEY_PREFIX}${userId}`
}

/** Resolve the active user id from persisted auth state. '' if none. */
export function getCurrentUserId(): string {
  try {
    const raw = localStorage.getItem(AUTH_USER_LS_KEY)
    if (!raw) return ''
    const parsed = JSON.parse(raw)
    return (parsed && typeof parsed.id === 'string') ? parsed.id : ''
  } catch {
    return ''
  }
}

/** Save every registered global pointer into the user's scoped slot.
 *  Called when a user is about to stop being the active session
 *  (logout, account switch). */
export function persistActiveStateForUser(userId: string): void {
  if (!userId) return
  for (const base of registry) {
    try {
      const current = localStorage.getItem(base)
      if (current !== null) {
        localStorage.setItem(userScopedKey(base, userId), current)
      }
    } catch {
      // localStorage can throw (quota, private mode). Non-fatal.
    }
  }
}

/** Restore the user's previously-saved pointers into the global slots used
 *  by the UI. If the user has no saved state, the global slot is cleared
 *  so the incoming session starts clean. */
export function restoreActiveStateForUser(userId: string): void {
  if (!userId) return
  for (const base of registry) {
    try {
      const saved = localStorage.getItem(userScopedKey(base, userId))
      if (saved !== null) {
        localStorage.setItem(base, saved)
      } else {
        localStorage.removeItem(base)
      }
    } catch {
      // Non-fatal.
    }
  }
}

/** Wipe every registered global pointer. Used at logout, after the outgoing
 *  user's state has already been persisted into their scoped slot. */
export function clearActiveUiState(): void {
  for (const base of registry) {
    try { localStorage.removeItem(base) } catch { /* non-fatal */ }
  }
}

// ── Pre-registered application-wide pointers ────────────────────────────────
// These are the UI state keys that must never bleed across accounts. Feature
// modules may still register additional keys at their own module load.
registerUserScopedKey('homepilot_conversation')
registerUserScopedKey('homepilot_current_project')
registerUserScopedKey('homepilot_imagine_items')
registerUserScopedKey('homepilot_personality_id')
