/**
 * AuthScreen — Login / Register screen.
 *
 * Shown when no active user session. Minimalist, Claude-inspired design.
 * Supports: login, register, passwordless single-user auto-login,
 * smooth post-logout transition, and quick-switch via recent accounts.
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
    // Focus the password field after a tick
    setTimeout(() => {
      const pwInput = document.getElementById('auth-password-input')
      pwInput?.focus()
    }, 50)
  }

  const filteredRecent = (recentUsers || []).filter(u => u.username !== username)
  const showRecentUsers = mode === 'login' && filteredRecent.length > 0

  // Input shared styles
  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '10px 12px 10px 36px',
    borderRadius: 8,
    border: '1px solid rgba(148, 163, 184, 0.15)',
    background: 'rgba(15, 23, 42, 0.5)',
    color: '#e2e8f0',
    fontSize: 14,
    outline: 'none',
    boxSizing: 'border-box',
    transition: 'border-color 0.2s',
  }

  const inputStyleNoIcon: React.CSSProperties = {
    ...inputStyle,
    paddingLeft: 12,
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #0a0a1a 0%, #111827 50%, #0f172a 100%)',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      padding: '20px',
    }}>
      {/* Logo / Title */}
      <div style={{ marginBottom: 32, textAlign: 'center' }}>
        <h1 style={{
          fontSize: 28,
          fontWeight: 700,
          color: '#e2e8f0',
          margin: 0,
          letterSpacing: '-0.5px',
        }}>
          HomePilot
        </h1>
        <p style={{ color: '#64748b', fontSize: 14, marginTop: 8 }}>
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
          background: 'rgba(34, 197, 94, 0.1)',
          border: '1px solid rgba(34, 197, 94, 0.2)',
          marginBottom: 20,
          fontSize: 14,
          color: '#86efac',
          maxWidth: 400,
          width: '100%',
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
              color: '#86efac',
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

      {/* Recent accounts — quick switch (Google-style) */}
      {showRecentUsers && (
        <div style={{
          width: '100%',
          maxWidth: 400,
          marginBottom: 16,
          background: 'rgba(30, 41, 59, 0.6)',
          border: '1px solid rgba(148, 163, 184, 0.08)',
          borderRadius: 14,
          overflow: 'hidden',
          backdropFilter: 'blur(8px)',
        }}>
          <div style={{
            padding: '12px 16px 8px',
            fontSize: 11,
            fontWeight: 600,
            color: '#64748b',
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
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
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
                    border: '2px solid rgba(148, 163, 184, 0.1)',
                  }}
                />
              ) : (
                <div style={{
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)',
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
                  color: '#e2e8f0',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {recent.display_name || recent.username}
                </div>
                <div style={{
                  fontSize: 12,
                  color: '#64748b',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  @{recent.username}
                </div>
              </div>
              <ChevronRight size={16} style={{ color: '#475569', flexShrink: 0 }} />
            </button>
          ))}
        </div>
      )}

      {/* Card */}
      <div style={{
        width: '100%',
        maxWidth: 400,
        background: 'rgba(30, 41, 59, 0.8)',
        border: '1px solid rgba(148, 163, 184, 0.1)',
        borderRadius: 16,
        padding: 32,
        backdropFilter: 'blur(12px)',
      }}>
        {/* Tab switcher */}
        <div style={{
          display: 'flex',
          gap: 4,
          marginBottom: 24,
          background: 'rgba(15, 23, 42, 0.5)',
          borderRadius: 10,
          padding: 4,
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
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.2s',
                background: mode === m ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                color: mode === m ? '#93c5fd' : '#64748b',
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
            borderRadius: 8,
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.2)',
            marginBottom: 16,
            fontSize: 13,
            color: '#fca5a5',
          }}>
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Username */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6, fontWeight: 500 }}>
              Username
            </label>
            <div style={{ position: 'relative' }}>
              <User size={16} style={{ position: 'absolute', left: 12, top: 12, color: '#475569' }} />
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
                onFocus={e => (e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.4)')}
                onBlur={e => (e.currentTarget.style.borderColor = 'rgba(148, 163, 184, 0.15)')}
              />
            </div>
          </div>

          {/* Display Name (register only) */}
          {mode === 'register' && (
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6, fontWeight: 500 }}>
                Display Name <span style={{ color: '#475569' }}>(optional)</span>
              </label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="How should we call you?"
                maxLength={64}
                style={inputStyleNoIcon}
                onFocus={e => (e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.4)')}
                onBlur={e => (e.currentTarget.style.borderColor = 'rgba(148, 163, 184, 0.15)')}
              />
            </div>
          )}

          {/* Password */}
          <div style={{ marginBottom: mode === 'register' ? 16 : 24 }}>
            <label style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6, fontWeight: 500 }}>
              Password {mode === 'register' && <span style={{ color: '#475569' }}>(optional — skip for passwordless)</span>}
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
                onFocus={e => (e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.4)')}
                onBlur={e => (e.currentTarget.style.borderColor = 'rgba(148, 163, 184, 0.15)')}
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
                  color: '#475569',
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
              <label style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6, fontWeight: 500 }}>
                Email <span style={{ color: '#475569' }}>(optional — for password recovery)</span>
              </label>
              <div style={{ position: 'relative' }}>
                <Mail size={16} style={{ position: 'absolute', left: 12, top: 12, color: '#475569' }} />
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  maxLength={256}
                  style={inputStyle}
                  onFocus={e => (e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.4)')}
                  onBlur={e => (e.currentTarget.style.borderColor = 'rgba(148, 163, 184, 0.15)')}
                />
              </div>
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading || !username.trim()}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: 10,
              border: 'none',
              background: loading ? '#1e3a5f' : 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
              color: '#fff',
              fontSize: 15,
              fontWeight: 600,
              cursor: loading ? 'wait' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              transition: 'all 0.2s',
              opacity: (!username.trim() || loading) ? 0.5 : 1,
            }}
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
            borderRadius: 8,
            background: 'rgba(59, 130, 246, 0.08)',
            border: '1px solid rgba(59, 130, 246, 0.12)',
            fontSize: 12,
            color: '#93c5fd',
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
                color: '#60a5fa',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: 12,
                textDecoration: 'underline',
                padding: 0,
              }}
            >
              create a new account
            </button>
          </div>
        )}
      </div>

      {/* Footer */}
      <p style={{ color: '#475569', fontSize: 12, marginTop: 24 }}>
        Self-hosted &middot; Private &middot; Open Source
      </p>

      {/* Keyframe animation for the logout banner */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
