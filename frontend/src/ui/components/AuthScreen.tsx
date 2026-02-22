/**
 * AuthScreen — Login / Register screen.
 *
 * Shown when no active user session.
 * Design system: matches the main app's neutral dark palette.
 *
 * Color tokens (aligned with App.tsx / SettingsPanel / AccountMenu):
 *   Page bg:    #050506 (slightly deeper than --bg: hsl(0,0%,4%) = #0a0a0a)
 *   Card bg:    #141414 (matches elevated surfaces: #121212–#181818)
 *   Input bg:   rgba(255,255,255, 0.035) over card = app input style
 *   Borders:    rgba(255,255,255, 0.08) (matches white/10 in app)
 *   Primary:    #2563eb solid (blue-600, matches app buttons)
 *   Text:       white at 95/70/45/30 opacity (matches app hierarchy)
 */
import React, { useEffect, useState } from 'react'
import {
  User,
  LogIn,
  UserPlus,
  ArrowRight,
  Eye,
  EyeOff,
  Mail,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
} from 'lucide-react'
import type { AuthUser } from './AuthGate'
import type { RecentUser } from './AuthGate'

interface AuthScreenProps {
  backendUrl: string
  onAuthenticated: (user: AuthUser, token: string) => void
  /** Shown after a smooth logout (e.g. "Signed out as Alice") */
  logoutMessage?: string
  /** Previously logged-in accounts for quick switch */
  recentUsers?: RecentUser[]
}

export default function AuthScreen({
  backendUrl,
  onAuthenticated,
  logoutMessage,
  recentUsers,
}: AuthScreenProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showLogoutBanner, setShowLogoutBanner] = useState(!!logoutMessage)

  // Auto-dismiss logout banner after 5 seconds
  useEffect(() => {
    if (showLogoutBanner) {
      const timer = setTimeout(() => setShowLogoutBanner(false), 5000)
      return () => clearTimeout(timer)
    }
  }, [showLogoutBanner])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const endpoint = mode === 'login' ? '/v1/auth/login' : '/v1/auth/register'
      const body = mode === 'login'
        ? { username, password }
        : { username, password, email, display_name: displayName || username }

      const res = await fetch(`${backendUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })

      const data = await res.json()

      if (!res.ok) {
        setError(data.detail || 'Something went wrong')
        return
      }

      if (data.ok && data.token && data.user) {
        onAuthenticated(data.user, data.token)
      }
    } catch (err) {
      setError('Could not connect to the backend')
    } finally {
      setLoading(false)
    }
  }

  /** Quick-login: prefill username from a recent account and focus password */
  const handleQuickSelect = (recentUser: RecentUser) => {
    setMode('login')
    setUsername(recentUser.username)
    setPassword('')
    setError('')
    setShowLogoutBanner(false)
    setTimeout(() => {
      const pwInput = document.getElementById('auth-password-input')
      pwInput?.focus()
    }, 50)
  }

  const filteredRecent = (recentUsers || []).filter(u => u.username !== username)
  const showRecentUsers = mode === 'login' && filteredRecent.length > 0

  // ── Design tokens (app-consistent) ──────────────────────────────────────────
  const T = {
    pageBg:       '#050506',
    cardBg:       '#141414',
    inputBg:      'rgba(255, 255, 255, 0.035)',
    inputBgFocus: 'rgba(255, 255, 255, 0.055)',
    border:       'rgba(255, 255, 255, 0.08)',
    borderFocus:  'rgba(255, 255, 255, 0.18)',
    borderSubtle: 'rgba(255, 255, 255, 0.05)',
    // Text
    textPrimary:   'rgba(255, 255, 255, 0.95)',
    textSecondary: 'rgba(255, 255, 255, 0.70)',
    textMuted:     'rgba(255, 255, 255, 0.45)',
    textFaint:     'rgba(255, 255, 255, 0.30)',
    textPlaceholder: 'rgba(255, 255, 255, 0.22)',
    // Accent
    blue:         '#2563eb',
    blueHover:    '#3b82f6',
    blueSubtle:   'rgba(37, 99, 235, 0.12)',
    blueBorder:   'rgba(37, 99, 235, 0.25)',
    blueText:     'rgba(147, 197, 253, 0.90)',  // light blue for links
    // Status
    green:        'rgba(34, 197, 94, 0.12)',
    greenBorder:  'rgba(34, 197, 94, 0.25)',
    greenText:    '#86efac',
    red:          'rgba(239, 68, 68, 0.10)',
    redBorder:    'rgba(239, 68, 68, 0.20)',
    redText:      '#fca5a5',
    // Surfaces
    recentBg:     '#111111',
    tabBg:        'rgba(255, 255, 255, 0.03)',
    tabActive:    'rgba(37, 99, 235, 0.15)',
    // Misc
    icon:         'rgba(255, 255, 255, 0.25)',
    font:         'Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
  }

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '11px 12px 11px 38px',
    borderRadius: 10,
    border: `1px solid ${T.border}`,
    background: T.inputBg,
    color: T.textPrimary,
    fontSize: 14,
    outline: 'none',
    boxSizing: 'border-box',
    transition: 'border-color 0.2s, background 0.2s',
    fontFamily: T.font,
  }

  const inputStyleNoIcon: React.CSSProperties = {
    ...inputStyle,
    paddingLeft: 12,
  }

  const focusHandlers = {
    onFocus: (e: React.FocusEvent<HTMLInputElement>) => {
      e.currentTarget.style.borderColor = T.borderFocus
      e.currentTarget.style.background = T.inputBgFocus
    },
    onBlur: (e: React.FocusEvent<HTMLInputElement>) => {
      e.currentTarget.style.borderColor = T.border
      e.currentTarget.style.background = T.inputBg
    },
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: T.pageBg,
      fontFamily: T.font,
      padding: '20px',
    }}>
      {/* Subtle decorative glow — behind card, not competing */}
      <div style={{
        position: 'fixed',
        top: '35%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 600,
        height: 400,
        background: 'radial-gradient(ellipse, rgba(37, 99, 235, 0.04) 0%, transparent 70%)',
        pointerEvents: 'none',
        zIndex: 0,
      }} />

      {/* Logo / Title */}
      <div style={{ marginBottom: 36, textAlign: 'center', position: 'relative', zIndex: 1 }}>
        <h1 style={{
          fontSize: 30,
          fontWeight: 700,
          color: T.textPrimary,
          margin: 0,
          letterSpacing: '-0.5px',
        }}>
          HomePilot
        </h1>
        <p style={{ color: T.textMuted, fontSize: 14, marginTop: 8 }}>
          Your AI-Powered Creative Studio
        </p>
      </div>

      {/* Logout success banner */}
      {showLogoutBanner && logoutMessage && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '12px 20px',
          borderRadius: 12,
          background: T.green,
          border: `1px solid ${T.greenBorder}`,
          marginBottom: 20,
          fontSize: 14,
          color: T.greenText,
          maxWidth: 420,
          width: '100%',
          position: 'relative',
          zIndex: 1,
          animation: 'fadeIn 300ms ease-out',
        }}>
          <CheckCircle2 size={18} style={{ flexShrink: 0 }} />
          <span>{logoutMessage}</span>
          <button
            type="button"
            onClick={() => setShowLogoutBanner(false)}
            style={{
              marginLeft: 'auto',
              background: 'none',
              border: 'none',
              color: T.greenText,
              cursor: 'pointer',
              padding: 2,
              fontSize: 18,
              lineHeight: 1,
              opacity: 0.6,
            }}
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      )}

      {/* Recent accounts — quick switch */}
      {showRecentUsers && (
        <div style={{
          width: '100%',
          maxWidth: 420,
          marginBottom: 12,
          background: T.recentBg,
          border: `1px solid ${T.borderSubtle}`,
          borderRadius: 14,
          overflow: 'hidden',
          position: 'relative',
          zIndex: 1,
        }}>
          <div style={{
            padding: '12px 16px 8px',
            fontSize: 11,
            fontWeight: 600,
            color: T.textFaint,
            letterSpacing: '0.5px',
            textTransform: 'uppercase',
          }}>
            Recent Accounts
          </div>
          {filteredRecent.map((recent) => (
            <button
              key={recent.username}
              type="button"
              onClick={() => handleQuickSelect(recent)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 16px',
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                transition: 'background 0.15s',
                textAlign: 'left',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.04)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {/* Avatar */}
              {recent.avatar_url ? (
                <img
                  src={recent.avatar_url}
                  alt=""
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: '50%',
                    objectFit: 'cover',
                    border: `2px solid ${T.border}`,
                  }}
                />
              ) : (
                <div style={{
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  background: T.blue,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: 14,
                  fontWeight: 700,
                  flexShrink: 0,
                }}>
                  {(recent.display_name || recent.username).charAt(0).toUpperCase()}
                </div>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: T.textPrimary,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {recent.display_name || recent.username}
                </div>
                <div style={{
                  fontSize: 12,
                  color: T.textMuted,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  @{recent.username}
                </div>
              </div>
              <ChevronRight size={16} style={{ color: T.textFaint, flexShrink: 0 }} />
            </button>
          ))}
        </div>
      )}

      {/* Card — primary interaction surface */}
      <div style={{
        width: '100%',
        maxWidth: 420,
        background: T.cardBg,
        border: `1px solid ${T.border}`,
        borderRadius: 16,
        padding: '32px 28px',
        position: 'relative',
        zIndex: 1,
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5), 0 1px 4px rgba(0, 0, 0, 0.3)',
      }}>
        {/* Tab switcher */}
        <div style={{
          display: 'flex',
          gap: 4,
          marginBottom: 28,
          background: T.tabBg,
          borderRadius: 10,
          padding: 4,
          border: `1px solid ${T.borderSubtle}`,
        }}>
          {(['login', 'register'] as const).map(m => (
            <button
              key={m}
              onClick={() => { setMode(m); setError('') }}
              style={{
                flex: 1,
                padding: '10px 0',
                borderRadius: 8,
                border: 'none',
                fontSize: 13,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.2s',
                background: mode === m ? T.tabActive : 'transparent',
                color: mode === m ? T.blueText : T.textMuted,
              }}
            >
              {m === 'login' ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                  <LogIn size={14} /> Sign In
                </span>
              ) : (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                  <UserPlus size={14} /> Create Account
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 14px',
            borderRadius: 10,
            background: T.red,
            border: `1px solid ${T.redBorder}`,
            marginBottom: 16,
            fontSize: 13,
            color: T.redText,
          }}>
            <AlertCircle size={14} style={{ flexShrink: 0 }} />
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Username */}
          <div style={{ marginBottom: 18 }}>
            <label style={{ display: 'block', fontSize: 12, color: T.textMuted, marginBottom: 6, fontWeight: 500 }}>
              Username
            </label>
            <div style={{ position: 'relative' }}>
              <User size={16} style={{ position: 'absolute', left: 12, top: 12, color: T.icon }} />
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Enter username"
                required
                autoFocus={!showRecentUsers}
                minLength={2}
                maxLength={32}
                style={inputStyle}
                {...focusHandlers}
              />
            </div>
          </div>

          {/* Display Name (register only) */}
          {mode === 'register' && (
            <div style={{ marginBottom: 18 }}>
              <label style={{ display: 'block', fontSize: 12, color: T.textMuted, marginBottom: 6, fontWeight: 500 }}>
                Display Name <span style={{ color: T.textFaint }}>(optional)</span>
              </label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="How should we call you?"
                maxLength={64}
                style={inputStyleNoIcon}
                {...focusHandlers}
              />
            </div>
          )}

          {/* Password */}
          <div style={{ marginBottom: mode === 'register' ? 18 : 24 }}>
            <label style={{ display: 'block', fontSize: 12, color: T.textMuted, marginBottom: 6, fontWeight: 500 }}>
              Password {mode === 'register' && <span style={{ color: T.textFaint }}>(optional — skip for passwordless)</span>}
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="auth-password-input"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={mode === 'register' ? 'Leave empty for no password' : 'Enter password'}
                maxLength={128}
                style={{
                  ...inputStyleNoIcon,
                  paddingRight: 40,
                }}
                {...focusHandlers}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: 8,
                  background: 'none',
                  border: 'none',
                  color: T.icon,
                  cursor: 'pointer',
                  padding: 4,
                }}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Email (register only) */}
          {mode === 'register' && (
            <div style={{ marginBottom: 24 }}>
              <label style={{ display: 'block', fontSize: 12, color: T.textMuted, marginBottom: 6, fontWeight: 500 }}>
                Email <span style={{ color: T.textFaint }}>(optional — for password recovery)</span>
              </label>
              <div style={{ position: 'relative' }}>
                <Mail size={16} style={{ position: 'absolute', left: 12, top: 12, color: T.icon }} />
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  maxLength={256}
                  style={inputStyle}
                  {...focusHandlers}
                />
              </div>
            </div>
          )}

          {/* Submit — single authority blue */}
          <button
            type="submit"
            disabled={loading || !username.trim()}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: 10,
              border: 'none',
              background: T.blue,
              color: '#fff',
              fontSize: 15,
              fontWeight: 600,
              cursor: loading ? 'wait' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              transition: 'all 0.15s',
              opacity: (!username.trim() || loading) ? 0.4 : 1,
              fontFamily: T.font,
              letterSpacing: '0.01em',
            }}
            onMouseEnter={e => { if (username.trim() && !loading) e.currentTarget.style.background = T.blueHover }}
            onMouseLeave={e => { e.currentTarget.style.background = T.blue }}
          >
            {loading ? 'Please wait...' : mode === 'login' ? 'Sign In' : 'Create Account'}
            {!loading && <ArrowRight size={16} />}
          </button>
        </form>

        {/* Helpful hint when coming from logout */}
        {mode === 'login' && logoutMessage && (
          <div style={{
            marginTop: 16,
            padding: '10px 14px',
            borderRadius: 10,
            background: T.blueSubtle,
            border: `1px solid ${T.blueBorder}`,
            fontSize: 12,
            color: T.textSecondary,
            textAlign: 'center',
            lineHeight: 1.5,
          }}>
            Sign in with a different account or{' '}
            <button
              type="button"
              onClick={() => { setMode('register'); setError('') }}
              style={{
                background: 'none',
                border: 'none',
                color: T.blueText,
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: 12,
                textDecoration: 'underline',
                padding: 0,
                fontFamily: T.font,
              }}
            >
              create a new account
            </button>
          </div>
        )}
      </div>

      {/* Footer */}
      <p style={{ color: T.textFaint, fontSize: 12, marginTop: 24, position: 'relative', zIndex: 1 }}>
        Self-hosted &middot; Private &middot; Open Source
      </p>

      {/* Keyframe animation for the logout banner */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        /* Override browser autofill styling to match dark theme */
        input:-webkit-autofill,
        input:-webkit-autofill:hover,
        input:-webkit-autofill:focus {
          -webkit-box-shadow: 0 0 0 1000px #141414 inset !important;
          -webkit-text-fill-color: rgba(255, 255, 255, 0.95) !important;
          caret-color: rgba(255, 255, 255, 0.95) !important;
          transition: background-color 5000s ease-in-out 0s;
        }
        /* Placeholder color */
        input::placeholder {
          color: rgba(255, 255, 255, 0.22) !important;
        }
      `}</style>
    </div>
  )
}
