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
 */
import React, { useEffect, useState } from 'react'
import AuthScreen from './AuthScreen'
import OnboardingWizard from './OnboardingWizard'

interface AuthUser {
  id: string
  username: string
  display_name: string
  email: string
  onboarding_complete: boolean
}

interface AuthGateProps {
  children: React.ReactNode
}

const LS_TOKEN_KEY = 'homepilot_auth_token'
const LS_USER_KEY = 'homepilot_auth_user'

function getBackendUrl(): string {
  return localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000'
}

export default function AuthGate({ children }: AuthGateProps) {
  const [state, setState] = useState<'loading' | 'login' | 'onboarding' | 'ready'>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string>('')
  const backendUrl = getBackendUrl()

  useEffect(() => {
    checkAuth()
  }, [])

  async function checkAuth() {
    const savedToken = localStorage.getItem(LS_TOKEN_KEY) || ''
    const savedUser = localStorage.getItem(LS_USER_KEY)

    try {
      const res = await fetch(`${backendUrl}/v1/auth/me`, {
        headers: savedToken ? { 'Authorization': `Bearer ${savedToken}` } : {},
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

        if (!u.onboarding_complete) {
          setState('onboarding')
        } else {
          setState('ready')
        }
        return
      }

      // Fallback: let through
      setState('ready')
    } catch {
      // Backend unreachable — skip auth (backward compatible with pre-auth setups)
      setState('ready')
    }
  }

  function handleAuthenticated(u: AuthUser, t: string) {
    setUser(u)
    setToken(t)
    localStorage.setItem(LS_TOKEN_KEY, t)
    localStorage.setItem(LS_USER_KEY, JSON.stringify(u))

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

  // Loading spinner
  if (state === 'loading') {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a0a1a',
        color: '#64748b',
        fontFamily: 'system-ui, sans-serif',
        fontSize: 14,
      }}>
        Loading...
      </div>
    )
  }

  // Login / Register screen
  if (state === 'login') {
    return (
      <AuthScreen
        backendUrl={backendUrl}
        onAuthenticated={handleAuthenticated}
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

  // Authenticated and onboarded — render the main app
  return <>{children}</>
}
