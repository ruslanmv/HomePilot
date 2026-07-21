/**
 * AuthScreen — HomePilot Enterprise premium Sign-In / Sign-Up.
 *
 * Ported from the `sigin.html` design mockup into a wired React component.
 * Rendered by AuthGate when there is no active session. The AuthGate contract
 * is unchanged: this component receives `backendUrl` + `onAuthenticated` and,
 * on any successful auth, calls `onAuthenticated(user, token)` — every fetch
 * uses `credentials: 'include'` so the HttpOnly `homepilot_session` cookie flows.
 *
 * Controls wired here:
 *   • Continue with OllaBridge → federated token-exchange (Cloud login → POST
 *     /v1/auth/exchange). This is the buildable MVP of "Sign in with OllaBridge";
 *     the full Authorization-Code + PKCE redirect is the documented next step.
 *   • Sign in locally      → POST /v1/auth/login  (username OR email + password)
 *   • Create account modal → POST /v1/auth/register (local, passwordless allowed)
 *   • Use device code      → graceful device-pairing guidance (Cloud RFC 8628)
 *   • Forgot password?     → Cloud reset for federated accounts + local guidance
 *   • Terms / Privacy      → /terms and /privacy
 *
 * The design is kept self-contained: inline SVG + a scoped <style> block + a
 * <canvas> starfield. No external fonts/CDN. All CSS is scoped under `.hp-auth`
 * so nothing leaks into the rest of the app.
 */
import React, { useEffect, useRef, useState } from 'react'
import { isBffSessionEnabled } from '../account/featureFlags'
import type { AuthUser, RecentUser } from './AuthGate'

interface AuthScreenProps {
  backendUrl: string
  onAuthenticated: (user: AuthUser, token: string) => void
  /** Shown as a small banner after a smooth logout (e.g. "Signed out as Alice") */
  logoutMessage?: string
  /** Previously logged-in accounts — used to prefill the identifier field. */
  recentUsers?: RecentUser[]
}

/** Resolve the OllaBridge Cloud base URL (build-time env, else the shared default). */
function getCloudUrl(): string {
  const env: Record<string, string | undefined> =
    ((import.meta as unknown as { env?: Record<string, string | undefined> }).env) || {}
  const v = (env.VITE_OLLABRIDGE_CLOUD_URL || '').trim()
  return (v || 'https://ruslanmv-ollabridge.hf.space').replace(/\/+$/, '')
}

export default function AuthScreen({
  backendUrl,
  onAuthenticated,
  logoutMessage,
  recentUsers,
}: AuthScreenProps) {
  const cloudUrl = getCloudUrl()

  // ── Local sign-in state ──────────────────────────────────────────────────
  const [identifier, setIdentifier] = useState(
    (recentUsers && recentUsers[0]?.username) || '',
  )
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState<null | 'local' | 'ollabridge'>(null)

  // ── Modals ───────────────────────────────────────────────────────────────
  const [signupOpen, setSignupOpen] = useState(false)
  const [ollaOpen, setOllaOpen] = useState(false)
  const [infoModal, setInfoModal] = useState<null | 'device' | 'forgot'>(null)

  // ── Sign-up form state ───────────────────────────────────────────────────
  const [suUsername, setSuUsername] = useState('')
  const [suDisplay, setSuDisplay] = useState('')
  const [suPassword, setSuPassword] = useState('')
  const [suConfirm, setSuConfirm] = useState('')
  const [suEmail, setSuEmail] = useState('')
  const [suShowPassword, setSuShowPassword] = useState(false)
  const [suError, setSuError] = useState('')
  const [suLoading, setSuLoading] = useState(false)

  // ── OllaBridge federated form state ──────────────────────────────────────
  const [obEmail, setObEmail] = useState('')
  const [obPassword, setObPassword] = useState('')
  const [obError, setObError] = useState('')

  const openerRef = useRef<HTMLElement | null>(null)

  // Esc closes whichever overlay is open (restores focus to its opener).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      if (signupOpen) closeSignup()
      else if (ollaOpen) closeOlla()
      else if (infoModal) setInfoModal(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signupOpen, ollaOpen, infoModal])

  function rememberOpener() {
    openerRef.current = (document.activeElement as HTMLElement) || null
  }
  function restoreOpener() {
    setTimeout(() => openerRef.current?.focus?.(), 0)
  }

  function openSignup() {
    rememberOpener()
    setSuError('')
    setSignupOpen(true)
  }
  function closeSignup() {
    setSignupOpen(false)
    restoreOpener()
  }
  function openOlla() {
    rememberOpener()
    setObError('')
    setOllaOpen(true)
  }
  function closeOlla() {
    setOllaOpen(false)
    restoreOpener()
  }

  // ── Local login ──────────────────────────────────────────────────────────
  async function handleLocalLogin(e?: React.FormEvent) {
    e?.preventDefault()
    setError('')
    if (!identifier.trim()) {
      setError('Enter your username or email')
      return
    }
    setLoading('local')
    try {
      const res = await fetch(`${backendUrl}/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username: identifier.trim(), password }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Invalid username or password')
        return
      }
      if (data.ok && data.token && data.user) {
        onAuthenticated(data.user, data.token)
      } else {
        setError('Unexpected response from server')
      }
    } catch {
      setError('Could not connect to the backend')
    } finally {
      setLoading(null)
    }
  }

  // ── Create account (local) ───────────────────────────────────────────────
  async function handleSignup(e: React.FormEvent) {
    e.preventDefault()
    setSuError('')
    const username = suUsername.trim()
    if (!username) {
      setSuError('Username is required')
      return
    }
    // Passwordless is allowed (local-only). If a password IS set, enforce
    // min-8 and a confirm match.
    if (suPassword) {
      if (suPassword.length < 8) {
        setSuError('Password must be at least 8 characters')
        return
      }
      if (suPassword !== suConfirm) {
        setSuError('Passwords do not match')
        return
      }
    }
    setSuLoading(true)
    try {
      const res = await fetch(`${backendUrl}/v1/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          username,
          display_name: suDisplay.trim(),
          password: suPassword,
          email: suEmail.trim(),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setSuError(data.detail || 'Could not create account')
        return
      }
      if (data.ok && data.token && data.user) {
        closeSignup()
        onAuthenticated(data.user, data.token)
      } else {
        setSuError('Unexpected response from server')
      }
    } catch {
      setSuError('Could not connect to the backend')
    } finally {
      setSuLoading(false)
    }
  }

  // ── Continue with OllaBridge (federated token exchange) ──────────────────
  async function handleOllaSubmit(e: React.FormEvent) {
    e.preventDefault()
    setObError('')
    if (!obEmail.trim() || !obPassword) {
      setObError('Enter your OllaBridge email and password')
      return
    }
    setLoading('ollabridge')
    try {
      // 1) Authenticate against OllaBridge Cloud → receive a Cloud JWT.
      const loginRes = await fetch(`${cloudUrl}/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: obEmail.trim(), password: obPassword }),
      })
      const loginData = await loginRes.json().catch(() => ({}))
      if (!loginRes.ok || !loginData.token) {
        setObError(loginData.detail || 'Invalid OllaBridge email or password')
        return
      }
      // Keep the Cloud token for OllaBridge features beyond sign-in — the
      // Models tab uses it to sync models from the user's linked GPU nodes
      // and to route inference through the relay to their own machine.
      try {
        // Batch 7 (BFF): when the backend holds the cloud token server-side we
        // no longer persist it in the browser — the exchange POST below still
        // hands it to the backend. The (non-secret) cloud URL is kept.
        if (!isBffSessionEnabled()) localStorage.setItem('homepilot_cloud_token', loginData.token)
        localStorage.setItem('homepilot_cloud_url', cloudUrl)
      } catch { /* ignore */ }
      // 2) Exchange the Cloud token for a local HomePilot session (JIT-provision).
      const exRes = await fetch(`${backendUrl}/v1/auth/exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ cloud_token: loginData.token }),
      })
      const exData = await exRes.json().catch(() => ({}))
      if (!exRes.ok) {
        setObError(exData.detail || 'Could not link your OllaBridge account')
        return
      }
      if (exData.ok && exData.token && exData.user) {
        closeOlla()
        onAuthenticated(exData.user, exData.token)
      } else {
        setObError('Unexpected response from server')
      }
    } catch {
      setObError('Could not reach OllaBridge. Check your connection.')
    } finally {
      setLoading(null)
    }
  }

  // Premium single-column sign-in: the animated right panel and its starfield
  // canvas were removed in favor of a clean, static centered card.

  return (
    <div className="hp-auth">
      <style>{CSS}</style>

      <main className="page">
        {/* ---------------- LEFT ---------------- */}
        <section className="left" aria-label="HomePilot sign in">
          <div className="brand" aria-label="HomePilot">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120" fill="none">
              <defs>
                <linearGradient id="hp-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#06b6d4" />
                  <stop offset="50%" stopColor="#3b82f6" />
                  <stop offset="100%" stopColor="#8b5cf6" />
                </linearGradient>
                <linearGradient id="hp-accent" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#06b6d4" />
                  <stop offset="100%" stopColor="#8b5cf6" />
                </linearGradient>
                <filter id="hp-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="2" stdDeviation="6" floodColor="#3b82f6" floodOpacity="0.18" />
                </filter>
              </defs>
              <g filter="url(#hp-glow)" transform="translate(10, 10)">
                <path d="M50 12 L85 38 L85 88 L15 88 L15 38 Z" stroke="url(#hp-grad)" strokeWidth="3" fill="none" strokeLinejoin="round" />
                <path d="M50 12 L85 38" stroke="url(#hp-grad)" strokeWidth="3" strokeLinecap="round" />
                <path d="M50 12 L15 38" stroke="url(#hp-grad)" strokeWidth="3" strokeLinecap="round" />
                <rect x="38" y="60" width="24" height="28" rx="3" stroke="url(#hp-grad)" strokeWidth="2" fill="url(#hp-grad)" fillOpacity="0.1" />
                <circle cx="50" cy="48" r="10" fill="url(#hp-grad)" opacity="0.14" />
                <circle cx="50" cy="48" r="6" fill="url(#hp-grad)" opacity="0.36" />
                <circle cx="50" cy="48" r="2.5" fill="url(#hp-grad)" />
                <path d="M62 42 Q68 48 62 54" stroke="#06b6d4" strokeWidth="1.5" fill="none" strokeLinecap="round" opacity="0.36" />
                <path d="M66 38 Q74 48 66 58" stroke="#3b82f6" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.26" />
                <path d="M38 42 Q32 48 38 54" stroke="#06b6d4" strokeWidth="1.5" fill="none" strokeLinecap="round" opacity="0.36" />
                <path d="M34 38 Q26 48 34 58" stroke="#3b82f6" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.26" />
              </g>
              <text x="115" y="55" fontFamily="system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif" fontSize="38" fontWeight="800" letterSpacing="2">
                <tspan fill="#e2e8f0">Home</tspan><tspan fill="url(#hp-grad)">Pilot</tspan>
              </text>
              <text x="115" y="78" fontFamily="system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif" fontSize="12" fill="#94a3b8" letterSpacing="2.5">YOUR AI. YOUR DATA. YOUR RULES.</text>
              <rect x="115" y="85" width="80" height="2" rx="1" fill="url(#hp-accent)" opacity="0.36" />
            </svg>
          </div>

          <div className="form">
            <div className="pill">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 3l7 3v5c0 5-3 8.5-7 10-4-1.5-7-5-7-10V6l7-3Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                <path d="M9 12l2 2 4-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>You are signing into</span>
              <strong>HomePilot Enterprise</strong>
            </div>

            <h1>Sign in to HomePilot</h1>
            <p className="sub">Access your local AI workspace,<br />models, agents, memory, and tools.</p>

            {logoutMessage && (
              <div className="logout-banner" role="status">{logoutMessage}</div>
            )}

            <form className="stack" onSubmit={handleLocalLogin}>
              <button
                className="primary"
                type="button"
                onClick={openOlla}
                disabled={loading === 'ollabridge'}
              >
                <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
                  <path d="M15.2 31.4H12.8A8.8 8.8 0 0 1 4 22.6c0-4.86 3.94-8.8 8.8-8.8 1.13 0 2.22.22 3.2.61A12.5 12.5 0 0 1 39.9 20.6 7.9 7.9 0 0 1 37.6 36H17.8" stroke="white" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M18.5 29.8c3.7-4.05 7.24-4.05 10.93 0M14.8 35.2c6.18-7.1 12.23-7.1 18.4 0" stroke="white" strokeWidth="3.2" strokeLinecap="round" />
                </svg>
                <span>{loading === 'ollabridge' ? 'Connecting…' : 'Continue with OllaBridge'}</span>
              </button>

              <div className="divider">or use local access</div>

              <label className="field">
                <span className="ico" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none"><path d="M20 21a8 8 0 0 0-16 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /><circle cx="12" cy="7" r="4" stroke="currentColor" strokeWidth="1.8" /></svg>
                </span>
                <input
                  type="text"
                  autoComplete="username"
                  placeholder="Username or email"
                  aria-label="Username or email"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  autoFocus
                />
              </label>

              <label className="field">
                <span className="ico" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none"><rect x="4" y="10" width="16" height="10" rx="2.5" stroke="currentColor" strokeWidth="1.8" /><path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                </span>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="Password"
                  aria-label="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  className="eye"
                  type="button"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  onClick={() => setShowPassword((v) => !v)}
                >
                  <EyeSvg off={showPassword} />
                </button>
              </label>

              {error && <div className="err" role="alert">{error}</div>}

              <button className="local" type="submit" disabled={loading === 'local'}>
                {loading === 'local' ? 'Signing in…' : 'Sign in locally'}
              </button>

              <div className="links">
                <button type="button" className="linkbtn" onClick={() => setInfoModal('device')}>
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <rect x="3" y="3" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
                    <rect x="15" y="3" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
                    <rect x="3" y="15" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
                    <path d="M15 15h2v2h-2v-2Zm4 0h2v6h-6v-2h4v-4Z" fill="currentColor" />
                  </svg>
                  Use device code
                </button>
                <button type="button" className="linkbtn" onClick={() => setInfoModal('forgot')}>
                  Forgot password?
                </button>
              </div>

              <div className="signup-link-row">
                New to this device?
                <button type="button" id="openSignup" onClick={openSignup}>Create local account</button>
              </div>
            </form>
          </div>

          <p className="terms">
            By continuing, you agree to HomePilot's <a href="/terms">Terms of Service</a><br />
            and acknowledge our <a href="/privacy">Privacy Policy</a>.
          </p>
        </section>
      </main>

      {/* ---------------- CREATE ACCOUNT MODAL ---------------- */}
      <div
        className={`account-modal${signupOpen ? ' is-open' : ''}`}
        aria-hidden={!signupOpen}
        onMouseDown={(e) => { if (e.target === e.currentTarget) closeSignup() }}
      >
        <section className="account-dialog" role="dialog" aria-modal="true" aria-labelledby="signupTitle">
          <header className="account-header">
            <div className="account-title">
              <h2 id="signupTitle">Create Local Account</h2>
              <p>Create a local HomePilot account on this device. You can add a password now or keep it passwordless for a local-only setup.</p>
            </div>
            <button className="modal-close" type="button" aria-label="Close create account dialog" onClick={closeSignup}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </header>

          <form className="account-form" onSubmit={handleSignup}>
            <div className="modal-field">
              <label htmlFor="signupUsername">Username</label>
              <input id="signupUsername" type="text" autoComplete="username" placeholder="Enter username" required value={suUsername} onChange={(e) => setSuUsername(e.target.value)} />
            </div>

            <div className="modal-field">
              <label htmlFor="signupDisplay">Display Name <span className="hint">(optional)</span></label>
              <input id="signupDisplay" type="text" autoComplete="name" placeholder="How should we call you?" value={suDisplay} onChange={(e) => setSuDisplay(e.target.value)} />
            </div>

            <div className="modal-field">
              <label htmlFor="signupPassword">Password <span className="hint">(optional — skip for passwordless)</span></label>
              <div className="modal-password-wrap">
                <input id="signupPassword" type={suShowPassword ? 'text' : 'password'} autoComplete="new-password" placeholder="Leave empty for no password" value={suPassword} onChange={(e) => setSuPassword(e.target.value)} />
                <button className="modal-eye" type="button" aria-label={suShowPassword ? 'Hide account password' : 'Show account password'} onClick={() => setSuShowPassword((v) => !v)}>
                  <EyeSvg off={suShowPassword} small />
                </button>
              </div>
            </div>

            {suPassword && (
              <div className="modal-field">
                <label htmlFor="signupConfirm">Confirm Password</label>
                <input id="signupConfirm" type={suShowPassword ? 'text' : 'password'} autoComplete="new-password" placeholder="Re-enter your password" value={suConfirm} onChange={(e) => setSuConfirm(e.target.value)} />
              </div>
            )}

            <div className="modal-field">
              <label htmlFor="signupEmail">Email <span className="hint">(optional — for password recovery)</span></label>
              <input id="signupEmail" type="email" autoComplete="email" placeholder="your@email.com" value={suEmail} onChange={(e) => setSuEmail(e.target.value)} />
            </div>

            {suError && <div className="err" role="alert">{suError}</div>}

            <div className="modal-actions">
              <button className="create-button" type="submit" disabled={suLoading}>
                {suLoading ? 'Creating account…' : 'Create Local Account'}
              </button>
              <p className="modal-footnote">
                Local accounts stay on this HomePilot instance. For team identity and sync, use <strong>Continue with OllaBridge</strong>.
              </p>
            </div>
          </form>
        </section>
      </div>

      {/* ---------------- OLLABRIDGE FEDERATED MODAL ---------------- */}
      <div
        className={`account-modal${ollaOpen ? ' is-open' : ''}`}
        aria-hidden={!ollaOpen}
        onMouseDown={(e) => { if (e.target === e.currentTarget) closeOlla() }}
      >
        <section className="account-dialog" role="dialog" aria-modal="true" aria-labelledby="ollaTitle">
          <header className="account-header">
            <div className="account-title">
              <h2 id="ollaTitle">Continue with OllaBridge</h2>
              <p>Sign in with your OllaBridge Cloud account. HomePilot links it to a local profile — no second password stored here.</p>
            </div>
            <button className="modal-close" type="button" aria-label="Close OllaBridge sign-in dialog" onClick={closeOlla}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </header>

          <form className="account-form" onSubmit={handleOllaSubmit}>
            <div className="modal-field">
              <label htmlFor="obEmail">OllaBridge Email</label>
              <input id="obEmail" type="email" autoComplete="email" placeholder="you@company.com" required value={obEmail} onChange={(e) => setObEmail(e.target.value)} />
            </div>
            <div className="modal-field">
              <label htmlFor="obPassword">Password</label>
              <input id="obPassword" type="password" autoComplete="current-password" placeholder="Your OllaBridge password" required value={obPassword} onChange={(e) => setObPassword(e.target.value)} />
            </div>

            {obError && <div className="err" role="alert">{obError}</div>}

            <div className="modal-actions">
              <button className="create-button" type="submit" disabled={loading === 'ollabridge'}>
                {loading === 'ollabridge' ? 'Connecting…' : 'Continue'}
              </button>
              <p className="modal-footnote">
                No OllaBridge account?{' '}
                <a href={`${cloudUrl}/register`} target="_blank" rel="noopener noreferrer">Create one</a>{' '}— then return here to link it.
              </p>
            </div>
          </form>
        </section>
      </div>

      {/* ---------------- INFO MODALS (device code / forgot password) ---------------- */}
      <div
        className={`account-modal${infoModal ? ' is-open' : ''}`}
        aria-hidden={!infoModal}
        onMouseDown={(e) => { if (e.target === e.currentTarget) setInfoModal(null) }}
      >
        <section className="account-dialog" role="dialog" aria-modal="true" aria-labelledby="infoTitle">
          <header className="account-header">
            <div className="account-title">
              <h2 id="infoTitle">{infoModal === 'device' ? 'Use a device code' : 'Reset your password'}</h2>
              <p>
                {infoModal === 'device'
                  ? 'For TVs, CLIs and headless devices, pair through OllaBridge Cloud, then Continue with OllaBridge here.'
                  : 'Password reset depends on the account type.'}
              </p>
            </div>
            <button className="modal-close" type="button" aria-label="Close dialog" onClick={() => setInfoModal(null)}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </header>
          <div className="account-form">
            {infoModal === 'device' ? (
              <>
                <p className="info-body">
                  1. On this device, open <a href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer">{cloudUrl}/link</a> and sign in.<br />
                  2. Approve the device code shown on your other screen.<br />
                  3. Come back and use <strong>Continue with OllaBridge</strong> to finish.
                </p>
                <div className="modal-actions">
                  <a className="create-button linkish" href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer">Open OllaBridge pairing</a>
                </div>
              </>
            ) : (
              <>
                <p className="info-body">
                  <strong>OllaBridge accounts:</strong> reset your password on OllaBridge Cloud, then use Continue with OllaBridge.<br /><br />
                  <strong>Local accounts:</strong> HomePilot local accounts have no self-serve reset. Ask your instance administrator to set a new password from the Security settings, or create a new local account.
                </p>
                <div className="modal-actions">
                  <a className="create-button linkish" href={`${cloudUrl}/forgot-password`} target="_blank" rel="noopener noreferrer">Reset OllaBridge password</a>
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

/** Eye / eye-off SVG used by the password toggles. */
function EyeSvg({ off, small }: { off: boolean; small?: boolean }) {
  const s = small ? 20 : 23
  return (
    <svg viewBox="0 0 24 24" width={s} height={s} fill="none" aria-hidden="true">
      <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
      {off && <path d="M4 20L20 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />}
    </svg>
  )
}

// ── Scoped styles (ported from sigin.html, all selectors under `.hp-auth`) ──
const CSS = `
.hp-auth { --bg:#020307; --left:#080a0f; --ink:#f8fafc; --ink-2:rgba(226,232,240,.66);
  --cyan:#06b6d4; --blue:#3b82f6; --violet:#8b5cf6;
  --font:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  position:fixed; inset:0; z-index:0; overflow:auto;
  background:var(--bg); color:var(--ink); font-family:var(--font); }
.hp-auth *, .hp-auth *::before, .hp-auth *::after { box-sizing:border-box; }
.hp-auth button, .hp-auth input { font:inherit; }

/* Premium single-column layout: brand on top, one centered card. */
.hp-auth .page { min-height:100vh; display:grid; place-items:center; padding:34px 24px;
  background:
    radial-gradient(circle at 50% -8%, rgba(6,182,212,.09), transparent 34rem),
    radial-gradient(circle at 84% 88%, rgba(139,92,246,.075), transparent 30rem),
    radial-gradient(circle at 14% 90%, rgba(59,130,246,.055), transparent 26rem),
    #020307; }

.hp-auth .left { position:relative; z-index:5; width:min(452px,100%); display:flex;
  flex-direction:column; align-items:center; gap:24px; }

.hp-auth .brand { position:relative; z-index:1; width:232px; height:70px; }
.hp-auth .brand svg { width:100%; height:100%; display:block; }

.hp-auth .form { position:relative; z-index:1; width:100%; padding:38px 34px; overflow:hidden;
  border:1px solid rgba(255,255,255,.085); border-radius:24px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.04), transparent 18%),
    radial-gradient(circle at 0 0, rgba(6,182,212,.045), transparent 26%),
    radial-gradient(circle at 100% 100%, rgba(139,92,246,.055), transparent 30%),
    rgba(8,10,15,.93);
  box-shadow:0 34px 100px rgba(0,0,0,.52), 0 0 0 1px rgba(59,130,246,.025), inset 0 1px 0 rgba(255,255,255,.055);
  -webkit-backdrop-filter:blur(24px); backdrop-filter:blur(24px); }
.hp-auth .form::before { content:""; position:absolute; left:0; right:0; top:0; height:1px;
  background:linear-gradient(90deg, transparent, rgba(6,182,212,.52), rgba(59,130,246,.5), rgba(139,92,246,.48), transparent); }

.hp-auth .pill { width:max-content; max-width:100%; min-height:34px; margin:0 auto 20px; padding:0 14px;
  display:flex; align-items:center; gap:8px; border:1px solid rgba(255,255,255,.085); border-radius:999px;
  background:linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.014)), rgba(7,9,14,.56);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.05);
  color:rgba(226,232,240,.66); font-size:12.5px; }
.hp-auth .pill svg { width:15px; height:15px; color:var(--cyan); filter:drop-shadow(0 0 7px rgba(6,182,212,.34)); }
.hp-auth .pill strong { background:linear-gradient(90deg, var(--cyan), var(--blue), var(--violet));
  -webkit-background-clip:text; background-clip:text; color:transparent; font-weight:800; }

.hp-auth h1 { margin:0; text-align:center; font-weight:640; line-height:1.08; letter-spacing:-.045em;
  font-size:31px; }
.hp-auth .sub { width:min(360px,100%); margin:10px auto 26px; text-align:center; color:rgba(226,232,240,.64);
  font-size:14px; line-height:1.5; letter-spacing:-.01em; }

.hp-auth .logout-banner { width:min(440px,100%); margin:-18px auto 26px; text-align:center;
  padding:10px 14px; border-radius:12px; background:rgba(34,197,94,.10); border:1px solid rgba(34,197,94,.25);
  color:#86efac; font-size:14px; }

.hp-auth .stack { display:grid; gap:14px; }

.hp-auth .primary { position:relative; width:100%; min-height:52px; border:0; border-radius:13px; cursor:pointer;
  color:#fff; background:linear-gradient(135deg, #06b6d4, #3b82f6 48%, #8b5cf6);
  box-shadow:0 18px 48px rgba(59,130,246,.19), 0 16px 46px rgba(139,92,246,.16), inset 0 1px 0 rgba(255,255,255,.22);
  display:flex; align-items:center; justify-content:center; gap:10px; font-size:15px; font-weight:740;
  letter-spacing:-.02em; overflow:hidden; transition:transform .26s ease, box-shadow .32s ease, filter .32s ease; }
.hp-auth .primary:hover { transform:translateY(-1px); filter:brightness(1.06) saturate(1.04);
  box-shadow:0 22px 60px rgba(59,130,246,.24), 0 20px 58px rgba(139,92,246,.22), inset 0 1px 0 rgba(255,255,255,.25); }
.hp-auth .primary:disabled { opacity:.7; cursor:wait; }
.hp-auth .primary svg, .hp-auth .primary span { position:relative; z-index:1; }
.hp-auth .primary svg { width:22px; height:22px; }

.hp-auth .divider { display:grid; grid-template-columns:1fr auto 1fr; gap:12px; align-items:center;
  margin:22px 0 16px; color:rgba(148,163,184,.44); font-size:11px; font-weight:700;
  letter-spacing:.11em; text-transform:uppercase; }
.hp-auth .divider::before, .hp-auth .divider::after { content:""; height:1px;
  background:linear-gradient(90deg, transparent, rgba(148,163,184,.18), transparent); }

.hp-auth .field { position:relative; }
.hp-auth .field input { width:100%; height:52px; padding:0 48px; border:1px solid rgba(255,255,255,.10);
  border-radius:13px; background:linear-gradient(180deg, rgba(255,255,255,.032), rgba(255,255,255,.010)), rgba(5,7,11,.72);
  color:white; outline:none; font-size:15px; box-shadow:inset 0 1px 0 rgba(255,255,255,.03);
  transition:border-color .28s ease, box-shadow .28s ease, background .28s ease; }
.hp-auth .field input::placeholder { color:rgba(148,163,184,.55); }
.hp-auth .field input:focus { border-color:rgba(6,182,212,.42);
  box-shadow:0 0 0 4px rgba(6,182,212,.065), inset 0 1px 0 rgba(255,255,255,.06);
  background:linear-gradient(180deg, rgba(255,255,255,.050), rgba(255,255,255,.016)), rgba(4,6,10,.78); }
.hp-auth .ico, .hp-auth .eye { position:absolute; top:50%; transform:translateY(-50%); display:grid;
  place-items:center; color:rgba(148,163,184,.68); }
.hp-auth .ico { left:16px; }
.hp-auth .eye { right:12px; border:0; background:transparent; padding:4px; border-radius:8px; cursor:pointer;
  transition:background .22s ease, color .22s ease; }
.hp-auth .eye:hover { color:white; background:rgba(255,255,255,.05); }
.hp-auth .ico svg, .hp-auth .eye svg { width:19px; height:19px; }

.hp-auth .err { padding:10px 14px; border-radius:12px; background:rgba(239,68,68,.10);
  border:1px solid rgba(239,68,68,.24); color:#fca5a5; font-size:14px; }

.hp-auth .local { height:52px; border:1px solid rgba(139,92,246,.25); border-radius:13px; color:#c4b5fd;
  background:linear-gradient(180deg, rgba(139,92,246,.075), rgba(255,255,255,.012)), rgba(4,6,10,.74);
  cursor:pointer; font-weight:740; font-size:15px;
  transition:transform .24s ease, color .24s ease, border-color .24s ease, background .24s ease; }
.hp-auth .local:hover { transform:translateY(-1px); color:white; border-color:rgba(139,92,246,.30);
  background:linear-gradient(180deg, rgba(139,92,246,.065), rgba(255,255,255,.014)), rgba(4,6,10,.74); }
.hp-auth .local:disabled { opacity:.6; cursor:wait; }

.hp-auth .links { display:flex; align-items:center; justify-content:space-between; margin-top:16px; gap:18px; font-size:13px; }
.hp-auth .linkbtn { border:0; background:transparent; color:#a78bfa; cursor:pointer; padding:0;
  text-decoration:none; display:inline-flex; align-items:center; gap:8px; font-size:13px; transition:color .22s ease; }
.hp-auth .linkbtn:hover { color:white; }
.hp-auth .links svg { width:17px; height:17px; }

.hp-auth .signup-link-row { margin-top:22px; padding-top:20px; border-top:1px solid rgba(255,255,255,.08);
  text-align:center; color:rgba(148,163,184,.66); font-size:13px; }
.hp-auth .signup-link-row button { border:0; background:transparent; color:#a78bfa; cursor:pointer;
  font-weight:700; padding:2px 4px; border-radius:8px; transition:color .22s ease, background .22s ease; }
.hp-auth .signup-link-row button:hover { color:#fff; background:rgba(139,92,246,.10); }

.hp-auth .terms { position:relative; z-index:1; width:100%; margin:0; text-align:center;
  color:rgba(148,163,184,.52); font-size:11.5px; line-height:1.55; }
.hp-auth .terms a { color:#a78bfa; text-decoration:none; font-weight:650; }
.hp-auth .terms a:hover { text-decoration:underline; color:white; }

/* MODALS */
.hp-auth .account-modal { position:fixed; inset:0; z-index:50; display:grid; place-items:center; padding:24px;
  background:radial-gradient(circle at 50% 45%, rgba(59,130,246,.10), transparent 34%), rgba(0,0,0,.72);
  -webkit-backdrop-filter:blur(18px); backdrop-filter:blur(18px); opacity:0; pointer-events:none; transition:opacity .28s ease; }
.hp-auth .account-modal.is-open { opacity:1; pointer-events:auto; }
.hp-auth .account-dialog { width:min(520px, calc(100vw - 32px)); max-height:min(760px, calc(100vh - 32px)); overflow:auto;
  border-radius:24px; border:1px solid rgba(255,255,255,.11);
  background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.016)),
    radial-gradient(circle at 20% 0%, rgba(6,182,212,.08), transparent 28%),
    radial-gradient(circle at 95% 20%, rgba(139,92,246,.10), transparent 30%), #090b11;
  box-shadow:0 34px 120px rgba(0,0,0,.72), inset 0 1px 0 rgba(255,255,255,.08);
  transform:translateY(14px) scale(.985); transition:transform .34s cubic-bezier(.16,1,.3,1); }
.hp-auth .account-modal.is-open .account-dialog { transform:translateY(0) scale(1); }
.hp-auth .account-header { position:sticky; top:0; z-index:2; display:flex; align-items:flex-start; justify-content:space-between;
  gap:18px; padding:24px 24px 16px; background:linear-gradient(180deg, rgba(9,11,17,.98), rgba(9,11,17,.88));
  -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px); border-bottom:1px solid rgba(255,255,255,.07); }
.hp-auth .account-title { display:grid; gap:6px; }
.hp-auth .account-title h2 { margin:0; font-size:26px; line-height:1.05; letter-spacing:-.04em; font-weight:680; }
.hp-auth .account-title p { margin:0; color:rgba(226,232,240,.58); font-size:14px; line-height:1.45; }
.hp-auth .modal-close { width:38px; height:38px; border:1px solid rgba(255,255,255,.10); border-radius:12px;
  background:rgba(255,255,255,.035); color:rgba(226,232,240,.76); cursor:pointer; display:grid; place-items:center;
  transition:background .22s ease, color .22s ease, border-color .22s ease; flex-shrink:0; }
.hp-auth .modal-close:hover { background:rgba(255,255,255,.08); color:white; border-color:rgba(255,255,255,.18); }
.hp-auth .account-form { padding:22px 24px 24px; display:grid; gap:16px; }
.hp-auth .modal-field { display:grid; gap:8px; }
.hp-auth .modal-field label { color:rgba(248,250,252,.94); font-size:14px; font-weight:700; letter-spacing:-.01em; }
.hp-auth .modal-field .hint { color:rgba(148,163,184,.68); font-size:13px; line-height:1.38; font-weight:400; }
.hp-auth .modal-field input { width:100%; height:52px; padding:0 14px; border-radius:14px; border:1px solid rgba(255,255,255,.105);
  background:linear-gradient(180deg, rgba(255,255,255,.043), rgba(255,255,255,.014)), rgba(4,6,10,.74); color:white; outline:none;
  font-size:15px; transition:border-color .24s ease, box-shadow .24s ease, background .24s ease; }
.hp-auth .modal-field input::placeholder { color:rgba(148,163,184,.50); }
.hp-auth .modal-field input:focus { border-color:rgba(6,182,212,.44); box-shadow:0 0 0 4px rgba(6,182,212,.07);
  background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.018)), rgba(4,6,10,.82); }
.hp-auth .modal-password-wrap { position:relative; }
.hp-auth .modal-password-wrap input { padding-right:48px; }
.hp-auth .modal-eye { position:absolute; right:12px; top:50%; transform:translateY(-50%); width:34px; height:34px; border:0;
  border-radius:10px; color:rgba(148,163,184,.72); background:transparent; cursor:pointer; display:grid; place-items:center; }
.hp-auth .modal-eye:hover { color:white; background:rgba(255,255,255,.055); }
.hp-auth .modal-actions { display:grid; gap:12px; padding-top:6px; }
.hp-auth .create-button { height:54px; border:0; border-radius:15px; cursor:pointer; color:white; font-weight:800; font-size:16px;
  display:grid; place-items:center; text-decoration:none;
  background:linear-gradient(135deg, #06b6d4, #3b82f6 45%, #8b5cf6);
  box-shadow:0 18px 52px rgba(59,130,246,.16), 0 16px 50px rgba(139,92,246,.18), inset 0 1px 0 rgba(255,255,255,.22);
  transition:transform .24s ease, box-shadow .28s ease; }
.hp-auth .create-button:hover { transform:translateY(-1px);
  box-shadow:0 22px 64px rgba(59,130,246,.22), 0 20px 62px rgba(139,92,246,.24), inset 0 1px 0 rgba(255,255,255,.26); }
.hp-auth .create-button:disabled { opacity:.7; cursor:wait; }
.hp-auth .modal-footnote { margin:0; color:rgba(148,163,184,.58); font-size:12.5px; line-height:1.5; text-align:center; }
.hp-auth .modal-footnote strong { color:rgba(226,232,240,.78); font-weight:700; }
.hp-auth .modal-footnote a { color:#a78bfa; text-decoration:none; font-weight:700; }
.hp-auth .modal-footnote a:hover { text-decoration:underline; }
.hp-auth .info-body { margin:0; color:rgba(226,232,240,.74); font-size:14.5px; line-height:1.6; }
.hp-auth .info-body a { color:#a78bfa; text-decoration:none; font-weight:650; }
.hp-auth .info-body a:hover { text-decoration:underline; }

/* Tablet + mobile (< 980px): fast, static, single-column login. The animated
   right panel is hidden and the starfield canvas is never initialized (same
   980px threshold as the canvas effect guard) — login-first, low battery, big
   thumb targets. 100dvh (not 100vh) so mobile browser chrome can't clip it. */
@media (max-width:560px) {
  /* 100dvh (not 100vh) so mobile browser chrome can't clip the card. */
  .hp-auth .page { min-height:100dvh;
    padding:max(24px, env(safe-area-inset-top)) 18px max(24px, env(safe-area-inset-bottom)); }
  .hp-auth .brand { width:200px; height:60px; }
  .hp-auth .form { padding:30px 22px; border-radius:20px; }
  /* WCAG 2.2 target sizing — >=44px tap links. */
  .hp-auth .linkbtn { min-height:44px; }
  .hp-auth .links { align-items:flex-start; flex-direction:column; gap:12px; }

  /* Create-account modal becomes a bottom sheet on phones. */
  .hp-auth .account-modal { align-items:end; padding:0; }
  .hp-auth .account-dialog {
    width:100%; max-width:100%; max-height:92dvh;
    border-radius:24px 24px 0 0; transform:translateY(100%);
  }
  .hp-auth .account-modal.is-open .account-dialog { transform:translateY(0); }
  .hp-auth .account-form { padding-bottom:max(24px, env(safe-area-inset-bottom)); }
}
@media (prefers-reduced-motion: reduce) {
  .hp-auth *, .hp-auth *::before, .hp-auth *::after {
    animation-duration:.001ms !important; animation-iteration-count:1 !important; scroll-behavior:auto !important;
  }
}
`
