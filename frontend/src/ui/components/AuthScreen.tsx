/**
 * AuthScreen — Login / Register screen.
 *
 * Shown when no active user session. Minimalist, Claude-inspired design.
 * Supports: login, register, passwordless single-user auto-login.
 */
import React, { useState } from 'react'
import { User, LogIn, UserPlus, ArrowRight, Eye, EyeOff, Mail, AlertCircle } from 'lucide-react'
import type { AuthUser } from './AuthGate'

interface AuthScreenProps {
  backendUrl: string
  onAuthenticated: (user: AuthUser, token: string) => void
}

export default function AuthScreen({ backendUrl, onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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
                autoFocus
                minLength={2}
                maxLength={32}
                style={{
                  width: '100%',
                  padding: '10px 12px 10px 36px',
                  borderRadius: 8,
                  border: '1px solid rgba(148, 163, 184, 0.15)',
                  background: 'rgba(15, 23, 42, 0.5)',
                  color: '#e2e8f0',
                  fontSize: 14,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
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
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: '1px solid rgba(148, 163, 184, 0.15)',
                  background: 'rgba(15, 23, 42, 0.5)',
                  color: '#e2e8f0',
                  fontSize: 14,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          )}

          {/* Password */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6, fontWeight: 500 }}>
              Password {mode === 'register' && <span style={{ color: '#475569' }}>(optional — skip for passwordless)</span>}
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={mode === 'register' ? 'Leave empty for no password' : 'Enter password'}
                maxLength={128}
                style={{
                  width: '100%',
                  padding: '10px 40px 10px 12px',
                  borderRadius: 8,
                  border: '1px solid rgba(148, 163, 184, 0.15)',
                  background: 'rgba(15, 23, 42, 0.5)',
                  color: '#e2e8f0',
                  fontSize: 14,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
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
                  style={{
                    width: '100%',
                    padding: '10px 12px 10px 36px',
                    borderRadius: 8,
                    border: '1px solid rgba(148, 163, 184, 0.15)',
                    background: 'rgba(15, 23, 42, 0.5)',
                    color: '#e2e8f0',
                    fontSize: 14,
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
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
      </div>

      {/* Footer */}
      <p style={{ color: '#475569', fontSize: 12, marginTop: 24 }}>
        Self-hosted &middot; Private &middot; Open Source
      </p>
    </div>
  )
}
