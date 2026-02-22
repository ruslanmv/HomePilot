/**
 * OnboardingWizard — 3-step minimalist onboarding.
 *
 * Shown after first registration. Claude-inspired: clean, fast, no friction.
 * Step 1: Your name
 * Step 2: What you'll use HomePilot for + preferred tone
 * Step 3: Ready — welcome screen
 */
import React, { useState } from 'react'
import { ArrowRight, ArrowLeft, Check, Sparkles, MessageSquare, Image, Search, Heart, Film } from 'lucide-react'

interface OnboardingWizardProps {
  backendUrl: string
  token: string
  username: string
  onComplete: (displayName: string) => void
}

const USE_CASES = [
  { id: 'chat', label: 'Chat & Conversation', icon: MessageSquare, color: '#3b82f6' },
  { id: 'images', label: 'Image Generation', icon: Image, color: '#8b5cf6' },
  { id: 'research', label: 'Research & Knowledge', icon: Search, color: '#06b6d4' },
  { id: 'companion', label: 'AI Companion', icon: Heart, color: '#ec4899' },
  { id: 'content', label: 'Content Creation', icon: Film, color: '#f59e0b' },
]

const TONES = [
  { id: 'casual', label: 'Casual', desc: 'Friendly and relaxed' },
  { id: 'balanced', label: 'Balanced', desc: 'Natural and adaptable' },
  { id: 'professional', label: 'Professional', desc: 'Clear and formal' },
]

export default function OnboardingWizard({ backendUrl, token, username, onComplete }: OnboardingWizardProps) {
  const [step, setStep] = useState(1)
  const [displayName, setDisplayName] = useState('')
  const [selectedUseCases, setSelectedUseCases] = useState<string[]>([])
  const [tone, setTone] = useState('balanced')
  const [saving, setSaving] = useState(false)

  const toggleUseCase = (id: string) => {
    setSelectedUseCases(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const handleFinish = async () => {
    setSaving(true)
    try {
      await fetch(`${backendUrl}/v1/auth/onboarding`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        credentials: 'include',
        body: JSON.stringify({
          display_name: displayName.trim() || username,
          use_cases: selectedUseCases,
          preferred_tone: tone,
        }),
      })
    } catch {
      // Non-fatal — proceed anyway
    }
    setSaving(false)
    onComplete(displayName.trim() || username)
  }

  const cardStyle: React.CSSProperties = {
    width: '100%',
    maxWidth: 480,
    background: 'rgba(30, 41, 59, 0.8)',
    border: '1px solid rgba(148, 163, 184, 0.1)',
    borderRadius: 16,
    padding: 32,
    backdropFilter: 'blur(12px)',
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
      padding: 20,
    }}>
      {/* Progress dots */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {[1, 2, 3].map(s => (
          <div key={s} style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: s <= step ? '#3b82f6' : 'rgba(148, 163, 184, 0.2)',
            transition: 'background 0.3s',
          }} />
        ))}
      </div>

      {/* Step 1: Your name */}
      {step === 1 && (
        <div style={cardStyle}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <Sparkles size={32} style={{ color: '#3b82f6', marginBottom: 12 }} />
            <h2 style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>
              Welcome to HomePilot
            </h2>
            <p style={{ color: '#94a3b8', fontSize: 14, marginTop: 8 }}>
              Let's set up your profile so your AI companions know who you are.
            </p>
          </div>

          <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 8, fontWeight: 500 }}>
            What should we call you?
          </label>
          <input
            type="text"
            value={displayName}
            onChange={e => setDisplayName(e.target.value)}
            placeholder={username}
            autoFocus
            maxLength={64}
            style={{
              width: '100%',
              padding: '12px 14px',
              borderRadius: 10,
              border: '1px solid rgba(148, 163, 184, 0.15)',
              background: 'rgba(15, 23, 42, 0.5)',
              color: '#e2e8f0',
              fontSize: 16,
              outline: 'none',
              boxSizing: 'border-box',
              marginBottom: 24,
            }}
            onKeyDown={e => e.key === 'Enter' && setStep(2)}
          />

          <button
            onClick={() => setStep(2)}
            style={{
              width: '100%',
              padding: 12,
              borderRadius: 10,
              border: 'none',
              background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
              color: '#fff',
              fontSize: 15,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            Continue <ArrowRight size={16} />
          </button>
        </div>
      )}

      {/* Step 2: Use cases + tone */}
      {step === 2 && (
        <div style={cardStyle}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <h2 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>
              How will you use HomePilot?
            </h2>
            <p style={{ color: '#94a3b8', fontSize: 13, marginTop: 6 }}>
              Select all that apply — this helps personalize your experience.
            </p>
          </div>

          {/* Use case chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 24 }}>
            {USE_CASES.map(uc => {
              const selected = selectedUseCases.includes(uc.id)
              const Icon = uc.icon
              return (
                <button
                  key={uc.id}
                  onClick={() => toggleUseCase(uc.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '8px 14px',
                    borderRadius: 20,
                    border: `1.5px solid ${selected ? uc.color : 'rgba(148, 163, 184, 0.15)'}`,
                    background: selected ? `${uc.color}20` : 'transparent',
                    color: selected ? uc.color : '#94a3b8',
                    fontSize: 13,
                    fontWeight: 500,
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  <Icon size={14} />
                  {uc.label}
                  {selected && <Check size={12} />}
                </button>
              )
            })}
          </div>

          {/* Tone */}
          <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 8, fontWeight: 500 }}>
            Preferred conversation style
          </label>
          <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
            {TONES.map(t => (
              <button
                key={t.id}
                onClick={() => setTone(t.id)}
                style={{
                  flex: 1,
                  padding: '10px 8px',
                  borderRadius: 10,
                  border: `1.5px solid ${tone === t.id ? '#3b82f6' : 'rgba(148, 163, 184, 0.15)'}`,
                  background: tone === t.id ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                  color: tone === t.id ? '#93c5fd' : '#94a3b8',
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: 'pointer',
                  textAlign: 'center',
                  transition: 'all 0.2s',
                }}
              >
                <div>{t.label}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{t.desc}</div>
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setStep(1)}
              style={{
                padding: '12px 20px',
                borderRadius: 10,
                border: '1px solid rgba(148, 163, 184, 0.15)',
                background: 'transparent',
                color: '#94a3b8',
                fontSize: 14,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <ArrowLeft size={14} /> Back
            </button>
            <button
              onClick={() => setStep(3)}
              style={{
                flex: 1,
                padding: 12,
                borderRadius: 10,
                border: 'none',
                background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                color: '#fff',
                fontSize: 15,
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
              }}
            >
              Continue <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Ready */}
      {step === 3 && (
        <div style={cardStyle}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #2563eb 0%, #8b5cf6 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
            }}>
              <Check size={28} style={{ color: '#fff' }} />
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>
              You're all set{displayName ? `, ${displayName}` : ''}!
            </h2>
            <p style={{ color: '#94a3b8', fontSize: 14, marginTop: 8, lineHeight: 1.5 }}>
              Your profile is ready. Your AI companions will use this to personalize your experience over time.
            </p>
          </div>

          {/* Summary */}
          <div style={{
            background: 'rgba(15, 23, 42, 0.5)',
            borderRadius: 10,
            padding: 16,
            marginBottom: 24,
            fontSize: 13,
            color: '#94a3b8',
          }}>
            {displayName && <div>Name: <span style={{ color: '#e2e8f0' }}>{displayName}</span></div>}
            {selectedUseCases.length > 0 && (
              <div style={{ marginTop: 6 }}>
                Interests: <span style={{ color: '#e2e8f0' }}>
                  {selectedUseCases.map(id => USE_CASES.find(u => u.id === id)?.label).join(', ')}
                </span>
              </div>
            )}
            <div style={{ marginTop: 6 }}>
              Style: <span style={{ color: '#e2e8f0' }}>{TONES.find(t => t.id === tone)?.label}</span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setStep(2)}
              style={{
                padding: '12px 20px',
                borderRadius: 10,
                border: '1px solid rgba(148, 163, 184, 0.15)',
                background: 'transparent',
                color: '#94a3b8',
                fontSize: 14,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <ArrowLeft size={14} /> Back
            </button>
            <button
              onClick={handleFinish}
              disabled={saving}
              style={{
                flex: 1,
                padding: 12,
                borderRadius: 10,
                border: 'none',
                background: saving ? '#1e3a5f' : 'linear-gradient(135deg, #2563eb 0%, #8b5cf6 100%)',
                color: '#fff',
                fontSize: 15,
                fontWeight: 600,
                cursor: saving ? 'wait' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
              }}
            >
              {saving ? 'Saving...' : 'Start using HomePilot'}
              {!saving && <Sparkles size={16} />}
            </button>
          </div>
        </div>
      )}

      {/* Skip link */}
      {step < 3 && (
        <button
          onClick={handleFinish}
          style={{
            background: 'none',
            border: 'none',
            color: '#475569',
            fontSize: 13,
            cursor: 'pointer',
            marginTop: 16,
          }}
        >
          Skip for now
        </button>
      )}
    </div>
  )
}
