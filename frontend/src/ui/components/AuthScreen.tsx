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
        localStorage.setItem('homepilot_cloud_token', loginData.token)
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

  // ── Starfield canvas (calm, drifting, reduced-motion aware) ──────────────
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    // Only run the starfield where it belongs: large screens, motion allowed,
    // and not in data-saver mode. On phones/tablets the animated right panel is
    // hidden (CSS) AND the canvas is never initialized here — no GPU/battery
    // cost, faster first paint. Matches the < 980px layout collapse below.
    const bigScreen = window.matchMedia('(min-width: 980px)').matches
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const saveData = Boolean(
      (navigator as unknown as { connection?: { saveData?: boolean } }).connection?.saveData,
    )
    if (!bigScreen || reduceMotion || saveData) return
    const cv: HTMLCanvasElement = canvas

    function fit(c: HTMLCanvasElement) {
      const rect = c.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
      c.width = Math.max(1, Math.floor(rect.width * dpr))
      c.height = Math.max(1, Math.floor(rect.height * dpr))
      const ctx = c.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      return { ctx, width: rect.width, height: rect.height }
    }

    let state = fit(cv)
    const stars = Array.from({ length: 56 }, () => ({
      x: Math.random(),
      y: Math.random(),
      r: Math.random() * 1.1 + 0.25,
      vx: (Math.random() - 0.5) * 0.00005,
      vy: -(Math.random() * 0.00008 + 0.00002),
      t: Math.random(),
      phase: Math.random() * Math.PI * 2,
    }))
    let frame = 0
    let raf = 0
    let running = true

    function draw() {
      const { ctx, width, height } = state
      frame += 1
      ctx.clearRect(0, 0, width, height)

      const mist = ctx.createRadialGradient(
        width * 0.64, height * 0.5, 0,
        width * 0.64, height * 0.5, Math.max(width, height) * 0.65,
      )
      mist.addColorStop(0, 'rgba(59,130,246,0.018)')
      mist.addColorStop(0.48, 'rgba(139,92,246,0.010)')
      mist.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = mist
      ctx.fillRect(0, 0, width, height)

      for (const s of stars) {
        s.x += s.vx
        s.y += s.vy
        if (s.y < -0.04) { s.y = 1.04; s.x = Math.random() }
        if (s.x < -0.05) s.x = 1.05
        if (s.x > 1.05) s.x = -0.05

        const x = s.x * width
        const y = s.y * height
        const pulse = 0.72 + Math.sin(frame * 0.01 + s.phase) * 0.28

        let color = '255,255,255'
        if (s.t < 0.26) color = '6,182,212'
        else if (s.t < 0.52) color = '59,130,246'
        else if (s.t < 0.72) color = '139,92,246'

        const alpha = (0.045 + s.t * 0.11) * pulse
        ctx.beginPath()
        ctx.arc(x, y, s.r * pulse, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${color}, ${alpha})`
        ctx.shadowColor = `rgba(${color}, ${alpha * 1.15})`
        ctx.shadowBlur = 7
        ctx.fill()
        ctx.shadowBlur = 0
      }
      raf = running ? requestAnimationFrame(draw) : 0
    }

    function onResize() { state = fit(cv) }
    // Stop drawing while the tab is backgrounded; resume on return.
    function onVisibility() {
      running = !document.hidden
      if (running && !raf) raf = requestAnimationFrame(draw)
    }
    window.addEventListener('resize', onResize)
    document.addEventListener('visibilitychange', onVisibility)
    draw()

    return () => {
      window.removeEventListener('resize', onResize)
      document.removeEventListener('visibilitychange', onVisibility)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

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

        {/* ---------------- RIGHT ---------------- */}
        <section className="right" aria-label="Looping HomePilot build animation">
          <canvas id="stars" ref={canvasRef} aria-hidden="true" />
          <div className="build-wave" aria-hidden="true" />
          <div className="floor" aria-hidden="true" />

          <div className="stage" aria-hidden="true">
            <svg viewBox="0 0 400 400" fill="none">
              <defs>
                <linearGradient id="bigHpGrad" x1="50" y1="40" x2="350" y2="360" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stopColor="#06b6d4" />
                  <stop offset=".52" stopColor="#3b82f6" />
                  <stop offset="1" stopColor="#8b5cf6" />
                </linearGradient>
                <radialGradient id="coreGrad" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(200 190) rotate(90) scale(52)">
                  <stop stopColor="#ffffff" />
                  <stop offset=".24" stopColor="#06b6d4" />
                  <stop offset=".62" stopColor="#3b82f6" stopOpacity=".42" />
                  <stop offset="1" stopColor="#8b5cf6" stopOpacity="0" />
                </radialGradient>
                <linearGradient id="bigFill" x1="110" y1="70" x2="300" y2="330" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#06b6d4" stopOpacity=".045" />
                  <stop offset=".5" stopColor="#3b82f6" stopOpacity=".080" />
                  <stop offset="1" stopColor="#8b5cf6" stopOpacity=".080" />
                </linearGradient>
                <filter id="bigGlow" x="-45%" y="-45%" width="190%" height="190%">
                  <feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#06b6d4" floodOpacity=".10" />
                  <feDropShadow dx="0" dy="0" stdDeviation="16" floodColor="#3b82f6" floodOpacity=".10" />
                  <feDropShadow dx="0" dy="0" stdDeviation="30" floodColor="#8b5cf6" floodOpacity=".14" />
                </filter>
              </defs>
              <path className="logo-house trace" d="M200 52 L340 156 L340 356 L60 356 L60 156 Z" />
              <path className="logo-house roof-a" d="M200 52 L340 156" />
              <path className="logo-house roof-b" d="M200 52 L60 156" />
              <path className="logo-house body-fixed" d="M340 156 L340 356 L60 356 L60 156" />
              <rect className="logo-door" x="152" y="244" width="96" height="112" rx="13" />
              <circle className="core-halo" cx="200" cy="190" r="58" fill="url(#coreGrad)" />
              <circle className="core-middle" cx="200" cy="190" r="36" fill="url(#bigHpGrad)" opacity=".13" />
              <circle className="core-middle" cx="200" cy="190" r="22" fill="url(#bigHpGrad)" opacity=".38" />
              <circle className="core-dot" cx="200" cy="190" r="10" fill="url(#bigHpGrad)" />
              <path className="wave w1r" d="M248 166 Q272 190 248 214" stroke="#06b6d4" strokeWidth="6" />
              <path className="wave w2r" d="M266 150 Q306 190 266 230" stroke="#3b82f6" strokeWidth="5" />
              <path className="wave w3r" d="M282 134 Q340 190 282 246" stroke="#8b5cf6" strokeWidth="4" />
              <path className="wave w1l" d="M152 166 Q128 190 152 214" stroke="#06b6d4" strokeWidth="6" />
              <path className="wave w2l" d="M134 150 Q94 190 134 230" stroke="#3b82f6" strokeWidth="5" />
              <path className="wave w3l" d="M118 134 Q60 190 118 246" stroke="#8b5cf6" strokeWidth="4" />
            </svg>
          </div>

          <div className="chip c1">Your AI</div>
          <div className="chip c2">Your data</div>
          <div className="chip c3">Your rules</div>
          <div className="noise" aria-hidden="true" />
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
  --build:3.6s;
  position:fixed; inset:0; z-index:0; overflow:auto;
  background:var(--bg); color:var(--ink); font-family:var(--font); }
.hp-auth *, .hp-auth *::before, .hp-auth *::after { box-sizing:border-box; }
.hp-auth button, .hp-auth input { font:inherit; }

.hp-auth .page { min-height:100vh; display:grid;
  grid-template-columns:minmax(420px,50%) minmax(520px,50%);
  background:
    radial-gradient(circle at 18% 18%, rgba(6,182,212,.04), transparent 28%),
    radial-gradient(circle at 78% 68%, rgba(139,92,246,.04), transparent 36%),
    #020307; }

.hp-auth .left { position:relative; z-index:5; min-height:100vh; display:flex;
  flex-direction:column; padding:30px clamp(24px,7vw,120px) 34px;
  background:linear-gradient(90deg, rgba(255,255,255,.018), transparent 72%),
    radial-gradient(circle at 34% 12%, rgba(59,130,246,.055), transparent 32%), #080a0f;
  border-right:1px solid rgba(255,255,255,.065); overflow:hidden; }
.hp-auth .left::before { content:""; position:absolute; inset:0;
  background:linear-gradient(rgba(255,255,255,.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.014) 1px, transparent 1px);
  background-size:78px 78px; -webkit-mask-image:radial-gradient(circle at 50% 45%, #000, transparent 74%);
  mask-image:radial-gradient(circle at 50% 45%, #000, transparent 74%); opacity:.10; pointer-events:none; }

.hp-auth .brand { position:relative; z-index:1; width:245px; height:74px; opacity:0;
  animation:hpBrandIn 900ms ease-out forwards; }
.hp-auth .brand svg { width:100%; height:100%; display:block; }
@keyframes hpBrandIn { from { opacity:0; transform:translateY(6px);} to { opacity:1; transform:translateY(0);} }

.hp-auth .form { position:relative; z-index:1; width:min(520px,100%); margin:auto;
  transform:translateY(-14px); opacity:0; animation:hpFormIn 900ms cubic-bezier(.16,1,.3,1) 140ms forwards; }
@keyframes hpFormIn { from { opacity:0; transform:translateY(8px);} to { opacity:1; transform:translateY(-14px);} }

.hp-auth .pill { width:max-content; max-width:100%; min-height:42px; margin:0 auto 50px; padding:0 18px;
  display:flex; align-items:center; gap:10px; border:1px solid rgba(255,255,255,.085); border-radius:999px;
  background:linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.014)), rgba(7,9,14,.56);
  box-shadow:0 20px 60px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.05);
  -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px); color:rgba(226,232,240,.66); font-size:14px; }
.hp-auth .pill svg { width:18px; height:18px; color:var(--cyan); filter:drop-shadow(0 0 7px rgba(6,182,212,.34)); }
.hp-auth .pill strong { background:linear-gradient(90deg, var(--cyan), var(--blue), var(--violet));
  -webkit-background-clip:text; background-clip:text; color:transparent; font-weight:800; }

.hp-auth h1 { margin:0; text-align:center; font-weight:560; line-height:1.02; letter-spacing:-.065em;
  font-size:clamp(40px,4vw,55px); }
.hp-auth .sub { width:min(440px,100%); margin:18px auto 42px; text-align:center; color:rgba(226,232,240,.66);
  font-size:clamp(18px,1.45vw,23px); line-height:1.45; letter-spacing:-.028em; }

.hp-auth .logout-banner { width:min(440px,100%); margin:-18px auto 26px; text-align:center;
  padding:10px 14px; border-radius:12px; background:rgba(34,197,94,.10); border:1px solid rgba(34,197,94,.25);
  color:#86efac; font-size:14px; }

.hp-auth .stack { display:grid; gap:14px; }

.hp-auth .primary { position:relative; width:100%; min-height:62px; border:0; border-radius:16px; cursor:pointer;
  color:#fff; background:linear-gradient(135deg, #06b6d4, #3b82f6 45%, #8b5cf6);
  box-shadow:0 20px 58px rgba(59,130,246,.16), 0 18px 56px rgba(139,92,246,.16), inset 0 1px 0 rgba(255,255,255,.22);
  display:flex; align-items:center; justify-content:center; gap:14px; font-size:18px; font-weight:700;
  letter-spacing:-.025em; overflow:hidden; transition:transform .26s ease, box-shadow .32s ease, filter .32s ease; }
.hp-auth .primary::before { content:""; position:absolute; inset:-90%;
  background:linear-gradient(115deg, transparent 26%, rgba(255,255,255,.20), transparent 39%);
  transform:translateX(-58%) rotate(8deg); animation:hpSoftShine 2.4s ease-out 1s both; pointer-events:none; }
.hp-auth .primary:hover { transform:translateY(-1px); filter:saturate(1.04);
  box-shadow:0 24px 70px rgba(59,130,246,.22), 0 22px 68px rgba(139,92,246,.24), inset 0 1px 0 rgba(255,255,255,.25); }
.hp-auth .primary:disabled { opacity:.7; cursor:wait; }
.hp-auth .primary svg, .hp-auth .primary span { position:relative; z-index:1; }
.hp-auth .primary svg { width:32px; height:32px; }
@keyframes hpSoftShine { 0% { transform:translateX(-62%) rotate(8deg); opacity:0;} 18% { opacity:1;} 100% { transform:translateX(72%) rotate(8deg); opacity:0;} }

.hp-auth .divider { display:grid; grid-template-columns:1fr auto 1fr; gap:16px; align-items:center;
  margin:28px 0 18px; color:rgba(148,163,184,.40); font-size:15px; }
.hp-auth .divider::before, .hp-auth .divider::after { content:""; height:1px;
  background:linear-gradient(90deg, transparent, rgba(148,163,184,.18), transparent); }

.hp-auth .field { position:relative; }
.hp-auth .field input { width:100%; height:60px; padding:0 58px; border:1px solid rgba(255,255,255,.10);
  border-radius:14px; background:linear-gradient(180deg, rgba(255,255,255,.038), rgba(255,255,255,.012)), rgba(4,6,10,.70);
  color:white; outline:none; font-size:16px; box-shadow:inset 0 1px 0 rgba(255,255,255,.045);
  transition:border-color .28s ease, box-shadow .28s ease, background .28s ease; }
.hp-auth .field input::placeholder { color:rgba(148,163,184,.55); }
.hp-auth .field input:focus { border-color:rgba(6,182,212,.42);
  box-shadow:0 0 0 4px rgba(6,182,212,.065), inset 0 1px 0 rgba(255,255,255,.06);
  background:linear-gradient(180deg, rgba(255,255,255,.050), rgba(255,255,255,.016)), rgba(4,6,10,.78); }
.hp-auth .ico, .hp-auth .eye { position:absolute; top:50%; transform:translateY(-50%); display:grid;
  place-items:center; color:rgba(148,163,184,.68); }
.hp-auth .ico { left:22px; }
.hp-auth .eye { right:18px; border:0; background:transparent; padding:4px; border-radius:8px; cursor:pointer;
  transition:background .22s ease, color .22s ease; }
.hp-auth .eye:hover { color:white; background:rgba(255,255,255,.05); }
.hp-auth .ico svg, .hp-auth .eye svg { width:23px; height:23px; }

.hp-auth .err { padding:10px 14px; border-radius:12px; background:rgba(239,68,68,.10);
  border:1px solid rgba(239,68,68,.24); color:#fca5a5; font-size:14px; }

.hp-auth .local { height:60px; border:1px solid rgba(255,255,255,.10); border-radius:14px; color:#a78bfa;
  background:linear-gradient(180deg, rgba(255,255,255,.038), rgba(255,255,255,.012)), rgba(4,6,10,.70);
  cursor:pointer; font-weight:700; font-size:17px;
  transition:transform .24s ease, color .24s ease, border-color .24s ease, background .24s ease; }
.hp-auth .local:hover { transform:translateY(-1px); color:white; border-color:rgba(139,92,246,.30);
  background:linear-gradient(180deg, rgba(139,92,246,.065), rgba(255,255,255,.014)), rgba(4,6,10,.74); }
.hp-auth .local:disabled { opacity:.6; cursor:wait; }

.hp-auth .links { display:flex; align-items:center; justify-content:space-between; margin-top:20px; gap:20px; font-size:16px; }
.hp-auth .linkbtn { border:0; background:transparent; color:#a78bfa; cursor:pointer; padding:0;
  text-decoration:none; display:inline-flex; align-items:center; gap:10px; font-size:16px; transition:color .22s ease; }
.hp-auth .linkbtn:hover { color:white; }
.hp-auth .links svg { width:22px; height:22px; }

.hp-auth .signup-link-row { margin-top:12px; text-align:center; color:rgba(148,163,184,.62); font-size:15px; }
.hp-auth .signup-link-row button { border:0; background:transparent; color:#a78bfa; cursor:pointer;
  font-weight:700; padding:2px 4px; border-radius:8px; transition:color .22s ease, background .22s ease; }
.hp-auth .signup-link-row button:hover { color:#fff; background:rgba(139,92,246,.10); }

.hp-auth .terms { position:relative; z-index:1; width:min(520px,100%); margin:0 auto; padding-top:32px;
  border-top:1px solid rgba(255,255,255,.08); text-align:center; color:rgba(148,163,184,.60); font-size:14px;
  line-height:1.55; opacity:0; animation:hpFadeIn 800ms ease-out 420ms forwards; }
@keyframes hpFadeIn { to { opacity:1; } }
.hp-auth .terms a { color:#a78bfa; text-decoration:none; font-weight:650; }
.hp-auth .terms a:hover { text-decoration:underline; color:white; }

/* RIGHT */
.hp-auth .right { position:relative; min-height:100vh; overflow:hidden;
  background:radial-gradient(circle at 82% 40%, rgba(59,130,246,.08), transparent 24%),
    radial-gradient(circle at 62% 52%, rgba(139,92,246,.06), transparent 34%), #000; isolation:isolate; }
.hp-auth .right::before { content:""; position:absolute; inset:0; z-index:1;
  background:linear-gradient(90deg, rgba(0,0,0,.38), transparent 16%); pointer-events:none; }
.hp-auth #stars { position:absolute; inset:0; z-index:2; width:100%; height:100%; display:block; }

/* ── One-shot build (enterprise clean): the house draws itself once, settles,
   and HOLDS. No fade-out, no repeating cycle. Everything below runs a single
   pass with fill-mode "both", ending in the final built state. ─────────────── */
.hp-auth .stage { position:absolute; z-index:6; top:50%; left:52%; width:min(54vw,720px); height:min(54vw,720px);
  display:grid; place-items:center; transform:translate(-50%,-50%);
  filter:drop-shadow(0 0 18px rgba(6,182,212,.10)) drop-shadow(0 0 34px rgba(139,92,246,.12));
  pointer-events:none; opacity:0; animation:hpStageIn 700ms ease-out both; }
@keyframes hpStageIn { from{opacity:0;} to{opacity:1;} }
.hp-auth .stage svg { width:100%; height:100%; overflow:visible; }

/* A single quiet energy sweep as the house draws, then gone — plays once. */
.hp-auth .build-wave { position:absolute; z-index:4; top:50%; left:52%; width:min(68vw,920px); height:min(44vw,580px);
  transform:translate(-50%,-50%); pointer-events:none; }
.hp-auth .build-wave::before { content:""; position:absolute; inset:0; border-radius:999px;
  background:radial-gradient(ellipse at 50% 50%, rgba(6,182,212,.14), rgba(59,130,246,.08) 30%, rgba(139,92,246,.05) 48%, transparent 70%);
  filter:blur(30px); transform:scale(.68,.42); opacity:0; animation:hpWaveGlow var(--build) ease-out both; }
.hp-auth .build-wave::after { content:""; position:absolute; left:6%; right:6%; top:48%; height:2px; border-radius:999px;
  background:linear-gradient(90deg, transparent, rgba(6,182,212,.56), rgba(59,130,246,.48), rgba(139,92,246,.42), transparent);
  filter:blur(.2px); transform-origin:left center; transform:scaleX(0); opacity:0; animation:hpWaveSweep var(--build) ease-out both; }
@keyframes hpWaveGlow { 0%{opacity:0; transform:scale(.5,.28);} 22%{opacity:.32; transform:scale(.9,.5);} 48%{opacity:.16; transform:scale(1.02,.56);} 72%,100%{opacity:0; transform:scale(1.06,.6);} }
@keyframes hpWaveSweep { 0%{transform:scaleX(0); opacity:0;} 14%{opacity:.85;} 44%{transform:scaleX(1); opacity:.45;} 64%,100%{transform:scaleX(1.04); opacity:0;} }

/* House lines draw sequentially, then hold at full opacity. */
.hp-auth .logo-house { stroke:url(#bigHpGrad); stroke-width:12; fill:none; stroke-linejoin:round; stroke-linecap:round; filter:url(#bigGlow); opacity:.9; }
.hp-auth .logo-door { stroke:url(#bigHpGrad); stroke-width:8; fill:url(#bigFill); opacity:0; animation:hpDoorReveal var(--build) ease-out both; }
.hp-auth .trace { stroke-dasharray:900; stroke-dashoffset:900; opacity:0; animation:hpHouseBuild var(--build) linear both; }
.hp-auth .roof-a, .hp-auth .roof-b, .hp-auth .body-fixed { stroke-dasharray:380; stroke-dashoffset:380; opacity:0; }
.hp-auth .roof-a { animation:hpLineBuildA var(--build) linear both; }
.hp-auth .roof-b { animation:hpLineBuildB var(--build) linear both; }
.hp-auth .body-fixed { stroke-dasharray:620; stroke-dashoffset:620; animation:hpLineBuildBody var(--build) linear both; }
@keyframes hpHouseBuild { 0%{stroke-dashoffset:900; opacity:0;} 12%{opacity:.35;} 60%,100%{stroke-dashoffset:0; opacity:.9;} }
@keyframes hpLineBuildA { 0%,8%{stroke-dashoffset:380; opacity:0;} 60%,100%{stroke-dashoffset:0; opacity:.9;} }
@keyframes hpLineBuildB { 0%,12%{stroke-dashoffset:380; opacity:0;} 64%,100%{stroke-dashoffset:0; opacity:.9;} }
@keyframes hpLineBuildBody { 0%,16%{stroke-dashoffset:620; opacity:0;} 68%,100%{stroke-dashoffset:0; opacity:.9;} }
@keyframes hpDoorReveal { 0%,46%{opacity:0; transform:translateY(8px);} 70%,100%{opacity:.8; transform:translateY(0);} }

/* Core node lights up once and stays lit. */
.hp-auth .core-halo { opacity:0; transform-origin:200px 190px; animation:hpCoreAppear var(--build) ease-out both; }
.hp-auth .core-middle, .hp-auth .core-dot { opacity:0; transform-origin:200px 190px; animation:hpCoreDotAppear var(--build) ease-out both; }
@keyframes hpCoreAppear { 0%,50%{opacity:0; transform:scale(.6);} 70%{opacity:.42; transform:scale(1.12);} 84%,100%{opacity:.34; transform:scale(1);} }
@keyframes hpCoreDotAppear { 0%,54%{opacity:0; transform:scale(.5);} 74%{opacity:1; transform:scale(1.1);} 86%,100%{opacity:1; transform:scale(1);} }

/* Signal arcs fade in once to a calm static level and hold (no pulsing). */
.hp-auth .wave { fill:none; stroke-linecap:round; opacity:0; stroke-dasharray:54 120; stroke-dashoffset:0; }
.hp-auth .w1l, .hp-auth .w1r { animation:hpSignal1 var(--build) ease-out both; }
.hp-auth .w2l, .hp-auth .w2r { animation:hpSignal2 var(--build) ease-out both; }
.hp-auth .w3l, .hp-auth .w3r { animation:hpSignal3 var(--build) ease-out both; }
@keyframes hpSignal1 { 0%,60%{opacity:0;} 80%,100%{opacity:.2;} }
@keyframes hpSignal2 { 0%,64%{opacity:0;} 84%,100%{opacity:.15;} }
@keyframes hpSignal3 { 0%,68%{opacity:0;} 88%,100%{opacity:.1;} }

.hp-auth .floor { position:absolute; z-index:5; left:12%; right:10%; bottom:14%; height:12%;
  background:radial-gradient(ellipse at center, rgba(6,182,212,.12), rgba(59,130,246,.10) 38%, rgba(139,92,246,.08) 56%, transparent 80%);
  filter:blur(24px); opacity:0; pointer-events:none; animation:hpFloorReveal var(--build) ease-out both; }
@keyframes hpFloorReveal { 0%,42%{opacity:0; transform:scaleX(.85);} 64%,100%{opacity:.42; transform:scaleX(1);} }

.hp-auth .chip { position:absolute; z-index:7; display:inline-flex; align-items:center; gap:9px; padding:10px 13px;
  border-radius:999px; border:1px solid rgba(255,255,255,.085); background:rgba(3,6,14,.28); color:rgba(226,232,240,.56);
  -webkit-backdrop-filter:blur(18px); backdrop-filter:blur(18px); font-size:13px; box-shadow:0 18px 58px rgba(0,0,0,.26); opacity:0; }
.hp-auth .chip::before { content:""; width:7px; height:7px; border-radius:999px;
  background:linear-gradient(135deg, var(--cyan), var(--violet)); box-shadow:0 0 12px rgba(6,182,212,.42); }
.hp-auth .c1 { left:12%; top:17%; animation:hpChip1 var(--build) ease-out both; }
.hp-auth .c2 { left:15%; bottom:22%; animation:hpChip2 var(--build) ease-out both; }
.hp-auth .c3 { right:12%; bottom:19%; animation:hpChip3 var(--build) ease-out both; }
@keyframes hpChip1 { 0%,66%{opacity:0; transform:translateY(8px);} 86%,100%{opacity:.92; transform:translateY(0);} }
@keyframes hpChip2 { 0%,72%{opacity:0; transform:translateY(8px);} 90%,100%{opacity:.92; transform:translateY(0);} }
@keyframes hpChip3 { 0%,78%{opacity:0; transform:translateY(8px);} 94%,100%{opacity:.92; transform:translateY(0);} }

.hp-auth .noise { position:absolute; inset:0; z-index:8; pointer-events:none; opacity:.022;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 320 320' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.78' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='320' height='320' filter='url(%23n)' opacity='.65'/%3E%3C/svg%3E");
  mix-blend-mode:overlay; }

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
@media (max-width:980px) {
  .hp-auth .page { display:block; min-height:100dvh; }
  .hp-auth .right { display:none; }
  .hp-auth .left {
    min-height:100dvh; border-right:0;
    padding:max(24px, env(safe-area-inset-top)) 22px max(28px, env(safe-area-inset-bottom));
  }
  .hp-auth .brand { width:200px; height:60px; }
  .hp-auth .form { margin:30px auto 34px; transform:none; }
  .hp-auth .pill { margin-bottom:28px; font-size:13px; }
  .hp-auth h1 { font-size:clamp(34px, 9vw, 44px); }
  .hp-auth .sub { margin:14px auto 30px; font-size:17px; }
  /* WCAG 2.2 target sizing — 56px controls, >=44px tap links. */
  .hp-auth .primary, .hp-auth .local { min-height:56px; }
  .hp-auth .field input { height:56px; }
  .hp-auth .linkbtn { min-height:44px; }

  /* Create-account modal becomes a bottom sheet on phones/tablets. */
  .hp-auth .account-modal { align-items:end; padding:0; }
  .hp-auth .account-dialog {
    width:100%; max-width:100%; max-height:92dvh;
    border-radius:24px 24px 0 0; transform:translateY(100%);
  }
  .hp-auth .account-modal.is-open .account-dialog { transform:translateY(0); }
  .hp-auth .account-form { padding-bottom:max(24px, env(safe-area-inset-bottom)); }
  .hp-auth .create-button { min-height:56px; }
}
@media (max-width:520px) {
  .hp-auth h1 { font-size:34px; }
  .hp-auth .sub { font-size:16px; }
  .hp-auth .links { align-items:flex-start; flex-direction:column; gap:12px; }
}
@media (prefers-reduced-motion: reduce) {
  .hp-auth *, .hp-auth *::before, .hp-auth *::after {
    animation-duration:.001ms !important; animation-iteration-count:1 !important; scroll-behavior:auto !important;
  }
}
`
