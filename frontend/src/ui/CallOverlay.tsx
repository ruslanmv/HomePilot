/**
 * CallOverlay.tsx — TSX port of the frontend/src/ui/phone/ design set.
 *
 * Maps 1:1 onto the design-only mockups in `phone/`:
 *   tokens.jsx       → HP_CALL + hpCallStateColor/Label (inlined below)
 *   icons.jsx        → <Icon* /> components
 *   controls.jsx     → <ControlBtn />
 *   avatar.jsx       → <CallAvatar />
 *   waveform.jsx     → <CallWaveform />
 *   call-modal.jsx   → <CallModal /> + the ModalPresentation wrapper
 *
 * Layered as a distinct "call mode" on top of the chat — it is NOT
 * the same thing as Voice mode:
 *   🎤 Voice  = input method inside the chat
 *   📞 Call   = a separate immersive session (this component)
 *
 * States (mirrors the designer's set):
 *   connecting · listening · thinking · speaking · muted
 *   (ended is intentionally short-lived — the overlay fades out.)
 *
 * This pass wires the visual shell. Real STT/TTS plumbing from
 * useVoiceController maps `listening/thinking/speaking` later.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'

export type CallState =
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'muted'
  | 'ended'

// ── Design tokens (ported from phone/tokens.jsx) ──────────────────

const HP_CALL = {
  font: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif',
  fontTabular: 'ui-monospace, SFMono-Regular, "Roboto Mono", Menlo, monospace',
  backdrop: 'rgba(5, 5, 6, 0.72)',
  surface: '#0b0b0c',
  surface2: '#121214',
  border: 'rgba(255, 255, 255, 0.08)',
  text: 'rgba(255, 255, 255, 0.92)',
  text2: 'rgba(255, 255, 255, 0.55)',
  text3: 'rgba(255, 255, 255, 0.35)',
  accent: '#22d3ee',
  stateListening: '#22d3ee',
  stateThinking: '#a78bfa',
  stateSpeaking: '#10b981',
  stateError: '#f87171',
  end: '#ef4444',
} as const

function hpCallStateColor(state: CallState): string {
  switch (state) {
    case 'listening': return HP_CALL.stateListening
    case 'thinking':  return HP_CALL.stateThinking
    case 'speaking':  return HP_CALL.stateSpeaking
    case 'connecting': return HP_CALL.accent
    case 'muted':
    case 'ended':     return HP_CALL.text3
    default:          return HP_CALL.text2
  }
}

function hpCallStateLabel(state: CallState): string {
  switch (state) {
    case 'connecting': return 'connecting'
    case 'listening':  return 'listening'
    case 'thinking':   return 'thinking'
    case 'speaking':   return 'speaking'
    case 'muted':      return 'microphone off'
    case 'ended':      return 'call ended'
    default:           return ''
  }
}

// ── Icons (ported from phone/icons.jsx) ───────────────────────────

type IconProps = { size?: number; color?: string }
const IconBase: React.FC<IconProps & { strokeWidth?: number; children: React.ReactNode }> = ({
  size = 20, color = 'currentColor', strokeWidth = 1.75, children,
}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth={strokeWidth}
    strokeLinecap="round" strokeLinejoin="round">
    {children}
  </svg>
)
const IconPhoneEnd: React.FC<IconProps> = (p) => (
  <IconBase {...p} strokeWidth={1.9}>
    <path d="M4 14c5-5 11-5 16 0l-2 2-3-1v-2a9 9 0 0 0-6 0v2l-3 1-2-2z" transform="rotate(135 12 12)" />
  </IconBase>
)
const IconMic: React.FC<IconProps> = (p) => (
  <IconBase {...p}>
    <rect x="9" y="3" width="6" height="12" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </IconBase>
)
const IconMicOff: React.FC<IconProps> = (p) => (
  <IconBase {...p}>
    <path d="M9 9V6a3 3 0 0 1 6 0v5m0 4a3 3 0 0 1-6 0" />
    <path d="M5 11a7 7 0 0 0 11.5 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3" />
    <path d="M3 3l18 18" />
  </IconBase>
)
const IconChat: React.FC<IconProps> = (p) => (
  <IconBase {...p}>
    <path d="M4 5h16v11H9l-5 4z" />
  </IconBase>
)
const IconBack: React.FC<IconProps> = (p) => (
  <IconBase {...p} strokeWidth={1.9}>
    <path d="M15 5l-7 7 7 7" />
  </IconBase>
)

// ── ControlBtn (ported from phone/controls.jsx) ───────────────────

type Tone = 'neutral' | 'danger' | 'start' | 'accent'
const ControlBtn: React.FC<{
  size?: number
  tone?: Tone
  active?: boolean
  disabled?: boolean
  label?: string
  ariaLabel?: string
  onClick?: () => void
  children: React.ReactNode
}> = ({
  size = 48, tone = 'neutral', active = false, disabled, label, ariaLabel, onClick, children,
}) => {
  const bg =
    tone === 'danger' ? HP_CALL.end :
    tone === 'start'  ? HP_CALL.stateSpeaking :
    tone === 'accent' ? HP_CALL.accent :
    active ? 'rgba(255,255,255,0.92)' : HP_CALL.surface2
  const fg =
    tone === 'danger' || tone === 'start' ? '#ffffff' :
    tone === 'accent' ? '#052c33' :
    active ? '#0b0b0c' : HP_CALL.text
  const glow =
    tone === 'danger' ? 'rgba(239, 68, 68, 0.45)' :
    tone === 'start'  ? 'rgba(16, 185, 129, 0.45)' :
    tone === 'accent' ? 'rgba(34, 211, 238, 0.4)' :
    'rgba(0, 0, 0, 0.3)'
  const border = tone === 'neutral' && !active ? `1px solid ${HP_CALL.border}` : 'none'

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
      opacity: disabled ? 0.45 : 1,
    }}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={ariaLabel || label || ''}
        style={{
          width: size, height: size, borderRadius: '50%',
          background: bg, border, color: fg, padding: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: disabled ? 'not-allowed' : 'pointer',
          boxShadow:
            tone === 'neutral' && !active
              ? 'inset 0 1px 0 rgba(255,255,255,0.04)'
              : `0 8px 22px ${glow}, inset 0 1px 0 rgba(255,255,255,0.12)`,
          transition: 'transform 80ms ease, background 120ms ease, box-shadow 120ms ease',
        }}
      >
        {children}
      </button>
      {label ? (
        <span style={{
          fontFamily: HP_CALL.font, fontSize: 11, fontWeight: 500, letterSpacing: 0.2,
          color: HP_CALL.text3, textTransform: 'lowercase',
        }}>{label}</span>
      ) : null}
    </div>
  )
}

// ── CallAvatar (ported from phone/avatar.jsx) ─────────────────────

const CallAvatar: React.FC<{
  size?: number
  state: CallState
  imageUrl?: string | null
  accentColor?: string | null
}> = ({ size = 156, state, imageUrl = null, accentColor = null }) => {
  const stateColor = hpCallStateColor(state)
  const breathes = state === 'listening' || state === 'connecting' || state === 'speaking'
  const haloOuter = size + 28

  const seed = (imageUrl || accentColor || 'homepilot').toString()
  const hue = useMemo(
    () => [...seed].reduce((a, c) => a + c.charCodeAt(0), 0) % 360,
    [seed],
  )

  return (
    <div style={{
      position: 'relative', width: haloOuter, height: haloOuter,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        position: 'absolute', inset: 0, borderRadius: '50%',
        background: `radial-gradient(circle, ${stateColor}55 0%, transparent 68%)`,
        filter: 'blur(14px)',
        opacity: breathes ? 0.8 : 0.35,
        animation: breathes ? 'hp-halo-breathe 2s ease-in-out infinite' : 'none',
      }} />
      <div style={{
        position: 'absolute', width: size + 10, height: size + 10,
        borderRadius: '50%',
        border: `2px solid ${stateColor}`,
        opacity: state === 'ended' || state === 'muted' ? 0.25 : 0.92,
      }} />
      <div style={{
        width: size, height: size, borderRadius: '50%',
        overflow: 'hidden', position: 'relative',
        background: imageUrl
          ? 'transparent'
          : `radial-gradient(circle at 35% 30%,
             hsl(${hue} 70% 55%) 0%,
             hsl(${(hue + 40) % 360} 50% 28%) 65%,
             hsl(${(hue + 80) % 360} 40% 12%) 100%)`,
        filter: state === 'ended' ? 'grayscale(0.6) brightness(0.7)' : 'none',
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.06), 0 0 0 1px rgba(255,255,255,0.04)',
      }}>
        {imageUrl ? (
          <img src={imageUrl} alt="" style={{
            width: '100%', height: '100%', objectFit: 'cover', display: 'block',
          }} />
        ) : (
          <div style={{
            position: 'absolute', inset: 0,
            background: 'radial-gradient(circle at 40% 25%, rgba(255,255,255,0.35) 0%, transparent 45%)',
          }} />
        )}
      </div>
    </div>
  )
}

// ── CallWaveform (ported from phone/waveform.jsx) ─────────────────

const CallWaveform: React.FC<{
  bars?: number
  height?: number
  state: CallState
  active?: boolean
  seed?: string
}> = ({ bars = 26, height = 24, state, active = true, seed = 'homepilot' }) => {
  const color = hpCallStateColor(state)
  const opacity = active ? 1 : 0.3
  const heights = useMemo(() => (
    Array.from({ length: bars }, (_, i) => {
      const n =
        Math.sin(i * 0.8 + seed.length) * 0.4 +
        Math.sin(i * 1.3 + seed.charCodeAt(0)) * 0.3 +
        0.55
      return active ? Math.max(0.15, Math.min(1, Math.abs(n))) : 0.08
    })
  ), [bars, seed, active])

  return (
    <div style={{
      display: 'flex', gap: 3, alignItems: 'center', justifyContent: 'center',
      height, opacity,
    }}>
      {heights.map((h, i) => (
        <div key={i} style={{
          width: 3, height: `${h * 100}%`,
          background: color, borderRadius: 2,
          opacity: active ? 0.5 + h * 0.45 : 0.4,
          transition: 'height 80ms linear, opacity 80ms linear',
        }} />
      ))}
    </div>
  )
}

// ── CallModal (ported from phone/call-modal.jsx) ──────────────────

interface CallModalProps {
  state: CallState
  personaName: string
  imageUrl?: string | null
  accentColor?: string | null
  durationSec: number
  onEnd: () => void
  onToggleMute: () => void
  onMinimize: () => void
  onSwitchToChat?: () => void
}

const CallModal: React.FC<CallModalProps> = ({
  state, personaName, imageUrl = null, accentColor = null,
  durationSec, onEnd, onToggleMute, onMinimize, onSwitchToChat,
}) => {
  const stateColor = hpCallStateColor(state)
  const stateLabel = hpCallStateLabel(state)
  const mm = Math.floor(durationSec / 60).toString().padStart(2, '0')
  const ss = (durationSec % 60).toString().padStart(2, '0')
  const timer = state === 'connecting' ? '—:—' : `${mm}:${ss}`

  return (
    <div style={{
      width: 'min(420px, 92vw)',
      padding: '18px 22px 26px',
      borderRadius: 24,
      background: HP_CALL.surface,
      border: `1px solid ${HP_CALL.border}`,
      boxShadow:
        '0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04)',
      position: 'relative', overflow: 'hidden',
      fontFamily: HP_CALL.font, color: HP_CALL.text,
      animation: 'hp-call-in 180ms ease-out',
    }}>
      <div style={{
        position: 'absolute', inset: '-40% -10% auto -10%', height: '60%',
        background: `radial-gradient(ellipse at 50% 100%, ${stateColor}26 0%, transparent 65%)`,
        pointerEvents: 'none', opacity: state === 'muted' ? 0.1 : 0.35,
      }} />

      {/* Header row */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', alignItems: 'center',
        height: 32, marginBottom: 10,
      }}>
        <button
          type="button"
          onClick={onMinimize}
          aria-label="Minimize call"
          style={{
            width: 32, height: 32, borderRadius: 10, padding: 0,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: HP_CALL.text2,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <IconBack size={18} color={HP_CALL.text2} />
        </button>
        <div style={{
          position: 'absolute', left: 40, right: 40, textAlign: 'center',
          fontSize: 16, fontWeight: 600, letterSpacing: -0.1,
          color: HP_CALL.text,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          pointerEvents: 'none',
        }}>{personaName}</div>
      </div>

      {/* Timer */}
      <div style={{
        position: 'relative', zIndex: 2, textAlign: 'center',
        fontSize: 13, color: HP_CALL.text2,
        fontFamily: HP_CALL.fontTabular,
        fontVariantNumeric: 'tabular-nums',
        marginBottom: 18,
      }}>{timer}</div>

      {/* Avatar + halo */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', justifyContent: 'center', marginBottom: 18,
      }}>
        <CallAvatar size={156} state={state} imageUrl={imageUrl} accentColor={accentColor} />
      </div>

      {/* State label + waveform/dots */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        gap: 10, marginBottom: 22, minHeight: 52,
      }}>
        {state === 'connecting' ? (
          <div style={{ display: 'flex', gap: 5 }}>
            {[0, 1, 2].map(i => (
              <div key={i} style={{
                width: 5, height: 5, borderRadius: '50%',
                background: HP_CALL.text,
                opacity: 0.35 + i * 0.2,
                animation: 'hp-dot-pulse 1s ease-in-out infinite',
                animationDelay: `${i * 0.12}s`,
              }} />
            ))}
          </div>
        ) : (
          <CallWaveform
            bars={26}
            height={24}
            state={state}
            active={state === 'listening' || state === 'speaking'}
            seed={personaName}
          />
        )}
        <div style={{
          fontSize: 14, fontWeight: 500, letterSpacing: 0.3,
          color: stateColor, textTransform: 'lowercase',
        }}>{stateLabel}</div>
      </div>

      {/* Three-button dock */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        gap: 28,
      }}>
        <ControlBtn
          size={56}
          active={state === 'muted'}
          ariaLabel={state === 'muted' ? 'Unmute microphone' : 'Mute microphone'}
          onClick={onToggleMute}
          disabled={state === 'connecting' || state === 'ended'}
        >
          {state === 'muted'
            ? <IconMicOff size={22} color="#0b0b0c" />
            : <IconMic size={22} />}
        </ControlBtn>

        <ControlBtn
          size={72} tone="danger" ariaLabel="End call"
          onClick={onEnd}
        >
          <IconPhoneEnd size={26} color="#ffffff" />
        </ControlBtn>

        <ControlBtn
          size={56} ariaLabel="Switch to text chat"
          onClick={onSwitchToChat}
          disabled={!onSwitchToChat || state === 'connecting' || state === 'ended'}
        >
          <IconChat size={22} />
        </ControlBtn>
      </div>
    </div>
  )
}

// ── Public overlay component ─────────────────────────────────────

export interface CallOverlayProps {
  open: boolean
  onClose: () => void
  /** Optional: the persona the user is calling (display only). */
  personaName?: string
  /** Optional: avatar URL for the orb. */
  avatarUrl?: string | null
  /** Optional: per-persona accent for the fallback aura. */
  accentColor?: string | null
  /** Optional: minimize handler — reserved for the future PIP. */
  onMinimize?: () => void
  /** Optional: "Switch to text chat" handler. */
  onSwitchToChat?: () => void
}

export default function CallOverlay({
  open, onClose,
  personaName = 'Assistant',
  avatarUrl = null,
  accentColor = null,
  onMinimize,
  onSwitchToChat,
}: CallOverlayProps) {
  const [state, setState] = useState<CallState>('connecting')
  const [muted, setMuted] = useState(false)
  const [durationSec, setDurationSec] = useState(0)

  // Reset + simulated connect on open.
  useEffect(() => {
    if (!open) return
    setState('connecting')
    setMuted(false)
    setDurationSec(0)
    const t = window.setTimeout(() => {
      setState((s) => (s === 'connecting' ? 'listening' : s))
    }, 1200)
    return () => window.clearTimeout(t)
  }, [open])

  // Live timer during active call.
  useEffect(() => {
    if (!open) return
    if (state === 'connecting' || state === 'ended') return
    const iv = window.setInterval(() => setDurationSec((n) => n + 1), 1000)
    return () => window.clearInterval(iv)
  }, [open, state])

  // Esc ends.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') handleEnd() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)

  }, [open])

  const handleEnd = useCallback(() => {
    setState('ended')
    window.setTimeout(() => onClose(), 180)
  }, [onClose])

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m
      setState((s) => {
        if (next) return 'muted'
        return s === 'muted' ? 'listening' : s
      })
      return next
    })
  }, [])

  const handleMinimize = useCallback(() => {
    if (onMinimize) onMinimize()
    else onClose()
  }, [onMinimize, onClose])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Call with ${personaName}`}
      className="fixed inset-0 z-[100] flex items-center justify-center"
    >
      <div
        className="absolute inset-0"
        style={{
          background: HP_CALL.backdrop,
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          transition: 'opacity 200ms ease',
          opacity: state === 'ended' ? 0 : 1,
        }}
      />
      <div className="relative z-10">
        <CallModal
          state={state}
          personaName={personaName}
          imageUrl={avatarUrl}
          accentColor={accentColor}
          durationSec={durationSec}
          onEnd={handleEnd}
          onToggleMute={toggleMute}
          onMinimize={handleMinimize}
          onSwitchToChat={onSwitchToChat}
        />
      </div>

      <style>{`
        @keyframes hp-call-in {
          from { opacity: 0; transform: scale(0.95); }
          to   { opacity: 1; transform: scale(1); }
        }
        @keyframes hp-halo-breathe {
          0%, 100% { opacity: 0.30; transform: scale(1); }
          50%      { opacity: 0.85; transform: scale(1.06); }
        }
        @keyframes hp-dot-pulse {
          0%, 100% { transform: translateY(0);   opacity: 0.35; }
          50%      { transform: translateY(-3px); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
