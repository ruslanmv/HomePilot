/**
 * AuthGate — wraps the entire app with authentication + onboarding.
 *
 * Flow:
 * 1. On mount, call GET /v1/auth/me to check auth status
 * 2. If needs_setup (no users) → show AuthScreen in register mode
 * 3. If needs_login (multi-user, no token) → show AuthScreen
 * 4. If authenticated but !onboarding_complete → show OnboardingWizard
 * 5. If authenticated and onboarded → render children (the main App)
 *
 * Single-user with no password: auto-login, no friction.
 *
 * Provides AuthContext so child components (e.g. App.tsx) can call
 * `logout()` for a smooth transition back to the login screen
 * without a hard page reload.
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import AuthScreen from './AuthScreen'
import OnboardingWizard from './OnboardingWizard'
import { resolveBackendUrl } from '../lib/backendUrl'

export interface AuthUser {
  id: string
  username: string
  display_name: string
  email: string
  avatar_url: string
  onboarding_complete: boolean
}

// ── Recent-users helpers (localStorage-backed) ────────────────────────────────
export interface RecentUser {
  username: string
  display_name: string
  avatar_url: string
  lastLogin: number // epoch ms
}

const LS_TOKEN_KEY = 'homepilot_auth_token'
const LS_USER_KEY = 'homepilot_auth_user'
const LS_RECENT_USERS_KEY = 'homepilot_recent_users'

function getBackendUrl(): string {
  return resolveBackendUrl()
}

function loadRecentUsers(): RecentUser[] {
  try {
    const raw = localStorage.getItem(LS_RECENT_USERS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as RecentUser[]
    // Sort by most recent first, keep max 5
    return parsed.sort((a, b) => b.lastLogin - a.lastLogin).slice(0, 5)
  } catch {
    return []
  }
}

function saveRecentUser(user: AuthUser) {
  const existing = loadRecentUsers().filter(u => u.username !== user.username)
  const entry: RecentUser = {
    username: user.username,
    display_name: user.display_name,
    avatar_url: user.avatar_url,
    lastLogin: Date.now(),
  }
  const updated = [entry, ...existing].slice(0, 5)
  localStorage.setItem(LS_RECENT_USERS_KEY, JSON.stringify(updated))
}

// ── Auth context ──────────────────────────────────────────────────────────────
interface AuthContextValue {
  user: AuthUser | null
  token: string
  logout: () => Promise<void>
  /** Merge partial updates into the current user (e.g. after avatar upload or profile save). */
  updateUser: (partial: Partial<AuthUser>) => void
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: '',
  logout: async () => {},
  updateUser: () => {},
})

export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}

// ── AuthGate component ────────────────────────────────────────────────────────
interface AuthGateProps {
  children: React.ReactNode
}

/** How long the first auth check may take before we stop waiting silently. A
 * sleeping Hugging Face Space can take tens of seconds to answer. */
export const AUTH_CHECK_TIMEOUT_MS = 25000
/** After this long, the startup screen explains the wait. */
export const SLOW_START_HINT_MS = 5000

export default function AuthGate({ children }: AuthGateProps) {
  const [state, setState] = useState<'loading' | 'login' | 'onboarding' | 'ready' | 'unreachable'>('loading')
  const [slowStart, setSlowStart] = useState(false)
  const [failure, setFailure] = useState<string>('')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string>('')
  const [loggedOutMessage, setLoggedOutMessage] = useState<string>('')
  const [recentUsers, setRecentUsers] = useState<RecentUser[]>([])
  const backendUrl = getBackendUrl()

  useEffect(() => {
    checkAuth()
  }, [])

  async function checkAuth() {
    const savedToken = localStorage.getItem(LS_TOKEN_KEY) || ''
    setState('loading')
    setSlowStart(false)
    setFailure('')
    const slowTimer = setTimeout(() => setSlowStart(true), SLOW_START_HINT_MS)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), AUTH_CHECK_TIMEOUT_MS)

    try {
      const res = await fetch(`${backendUrl}/v1/auth/me`, {
        headers: savedToken ? { 'Authorization': `Bearer ${savedToken}` } : {},
        credentials: 'include',
        signal: controller.signal,
      })

      if (!res.ok) {
        // Backend might not have the /v1/auth routes yet (old version)
        // → just let through (backward compatible)
        setState('ready')
        return
      }

      const data = await res.json()

      if (data.needs_setup) {
        // First boot — no users exist
        setState('login')
        return
      }

      if (data.needs_login) {
        // Multi-user, need to log in
        setRecentUsers(loadRecentUsers())
        setState('login')
        return
      }

      if (data.user) {
        const u = data.user as AuthUser
        const t = data.token || savedToken
        setUser(u)
        setToken(t)
        if (t) localStorage.setItem(LS_TOKEN_KEY, t)
        localStorage.setItem(LS_USER_KEY, JSON.stringify(u))
        saveRecentUser(u)

        if (!u.onboarding_complete) {
          setState('onboarding')
        } else {
          setState('ready')
        }
        return
      }

      // Fallback: let through
      setState('ready')
    } catch (e) {
      // The server didn't answer (still waking up, offline, or blocked). Say so
      // and offer Retry, instead of mounting an app that can't load anything —
      // which is how a phone ended up showing a blank black screen. "Continue
      // anyway" keeps the old pre-auth behaviour available.
      const aborted = (e as { name?: string } | null)?.name === 'AbortError'
      setFailure(aborted
        ? `The server didn't answer within ${Math.round(AUTH_CHECK_TIMEOUT_MS / 1000)} seconds.`
        : 'The server could not be reached.')
      console.error('[HomePilot] startup check failed', { backendUrl, aborted, error: String(e) })
      setState('unreachable')
    } finally {
      clearTimeout(slowTimer)
      clearTimeout(timeout)
    }
  }

  function handleAuthenticated(u: AuthUser, t: string) {
    setUser(u)
    setToken(t)
    setLoggedOutMessage('')
    localStorage.setItem(LS_TOKEN_KEY, t)
    localStorage.setItem(LS_USER_KEY, JSON.stringify(u))
    saveRecentUser(u)

    if (!u.onboarding_complete) {
      setState('onboarding')
    } else {
      setState('ready')
    }
  }

  function handleOnboardingComplete(displayName: string) {
    if (user) {
      const updated = { ...user, display_name: displayName, onboarding_complete: true }
      setUser(updated)
      localStorage.setItem(LS_USER_KEY, JSON.stringify(updated))
    }
    setState('ready')
  }

  // Update user fields live (e.g. after avatar upload or display name change)
  const updateUser = useCallback((partial: Partial<AuthUser>) => {
    setUser(prev => {
      if (!prev) return prev
      const updated = { ...prev, ...partial }
      localStorage.setItem(LS_USER_KEY, JSON.stringify(updated))
      // Also update recent-users cache so the login screen shows fresh data
      saveRecentUser(updated)
      return updated
    })
  }, [])

  // Smooth logout — clears state and transitions to login screen without reload
  const logout = useCallback(async () => {
    const savedToken = localStorage.getItem(LS_TOKEN_KEY) || ''
    const currentDisplayName = user?.display_name || user?.username || ''

    // Fire-and-forget backend invalidation
    if (savedToken) {
      try {
        await fetch(`${backendUrl}/v1/auth/logout`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${savedToken}` },
          credentials: 'include',
        })
      } catch { /* non-fatal */ }
    }

    // Clear stored credentials
    localStorage.removeItem(LS_TOKEN_KEY)
    localStorage.removeItem(LS_USER_KEY)

    // Transition smoothly
    setUser(null)
    setToken('')
    setLoggedOutMessage(
      currentDisplayName
        ? `Signed out as ${currentDisplayName}`
        : 'Signed out successfully'
    )
    setRecentUsers(loadRecentUsers())
    setState('login')
  }, [user, backendUrl])

  // Startup screen — clearly visible (the old one was 30%-opacity text on
  // near-black, which read as a blank black screen on phones), and honest
  // about a slow start.
  if (state === 'loading') {
    return (
      <div className="hp-status-screen" role="status" aria-live="polite">
        <div className="hp-status-card">
          <div className="hp-spinner" aria-hidden />
          <h1>Starting HomePilot…</h1>
          <p>{slowStart
            ? 'The server is waking up. On a sleeping Hugging Face Space this can take up to a minute.'
            : 'Connecting to your HomePilot server.'}</p>
        </div>
      </div>
    )
  }

  if (state === 'unreachable') {
    return (
      <div className="hp-status-screen" role="alert">
        <div className="hp-status-card">
          <div aria-hidden style={{ fontSize: 28 }}>📡</div>
          <h1>Can’t reach HomePilot</h1>
          <p>{failure} Check your connection, or wait a moment if the Space is starting, then try again.</p>
          <div className="hp-status-actions">
            <button type="button" className="hp-primary" onClick={() => { void checkAuth() }}>Retry</button>
            <button type="button" onClick={() => setState('ready')}>Continue anyway</button>
          </div>
        </div>
      </div>
    )
  }

  // Login / Register screen
  if (state === 'login') {
    return (
      <AuthScreen
        backendUrl={backendUrl}
        onAuthenticated={handleAuthenticated}
        logoutMessage={loggedOutMessage}
        recentUsers={recentUsers}
      />
    )
  }

  // Onboarding wizard
  if (state === 'onboarding' && user) {
    return (
      <OnboardingWizard
        backendUrl={backendUrl}
        token={token}
        username={user.username}
        onComplete={handleOnboardingComplete}
      />
    )
  }

  // Authenticated and onboarded — render the main app with auth context
  return (
    <AuthContext.Provider value={{ user, token, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  )
}
