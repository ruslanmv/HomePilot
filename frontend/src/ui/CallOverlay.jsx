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
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVoiceController } from './voice/useVoiceController';
import { useCallSession } from './call/useCallSession';
import Waveform from './phone/primitives/Waveform';
import Aura from './phone/primitives/Aura';
import { createStreamingTts } from './call/streamTts';
import { clog, speakOwned, isCallFullDuplexEnabled } from './call/log';
import { useBargeInDetector } from './call/bargeIn';
// ── Staged lifecycle timings. Numbers chosen so the user *feels* the
//    handshake instead of getting a hard screen flip: dial (ringing) →
//    connecting → listening (live). Dial is long enough for ~one full
//    PSTN ringback cadence (2 s on / 4 s off in the US) so the user
//    actually hears the phone "ring" before pickup.
const DIAL_MS = 2200; // 📞  "calling…"  — pulse-ring phase + one PSTN ring
const CONNECT_MS = 500; // 🔵  "connecting…" — dots-pulse phase
const END_FADE_MS = 220; // 🔴  end button → modal fade-out → onClose
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
};
function hpCallStateColor(state) {
    switch (state) {
        case 'listening': return HP_CALL.stateListening;
        case 'thinking': return HP_CALL.stateThinking;
        case 'speaking': return HP_CALL.stateSpeaking;
        case 'dialing':
        case 'connecting': return HP_CALL.accent;
        case 'muted':
        case 'ended': return HP_CALL.text3;
        default: return HP_CALL.text2;
    }
}
// Map the voice-controller's internal machine onto our UI machine.
// Returns null for states we don't want to reflect (OFF — overlay is
// open so "off" is not a meaningful UI frame; render last mapped).
function mapVoiceState(s) {
    switch (s) {
        case 'LISTENING': return 'listening';
        case 'THINKING': return 'thinking';
        case 'SPEAKING': return 'speaking';
        case 'IDLE': return 'listening';
        case 'OFF': return null;
        default: return null;
    }
}
// Map the overlay's richer CallState onto the primitive Waveform's
// four-valued mode enum. The primitive doesn't know about dialing /
// connecting / thinking — those all fold to 'idle' (low ambient
// amplitude, faint colour); only the three audible states drive
// distinct waveform modes.
function waveformModeFromCallState(state) {
    if (state === 'listening' || state === 'thinking')
        return 'listening';
    if (state === 'speaking')
        return 'speaking';
    if (state === 'muted')
        return 'muted';
    return 'idle';
}
function hpCallStateLabel(state, personaName) {
    switch (state) {
        case 'dialing': return `calling ${personaName.toLowerCase()}…`;
        case 'connecting': return 'connecting…';
        case 'listening': return 'listening';
        case 'thinking': return 'thinking';
        case 'speaking': return 'speaking';
        case 'muted': return 'microphone off';
        case 'ended': return 'call ended';
        default: return '';
    }
}
const IconBase = ({ size = 20, color = 'currentColor', strokeWidth = 1.75, children, }) => (<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    {children}
  </svg>);
const IconPhoneEnd = (p) => (<IconBase {...p} strokeWidth={1.9}>
    <path d="M4 14c5-5 11-5 16 0l-2 2-3-1v-2a9 9 0 0 0-6 0v2l-3 1-2-2z" transform="rotate(135 12 12)"/>
  </IconBase>);
const IconMic = (p) => (<IconBase {...p}>
    <rect x="9" y="3" width="6" height="12" rx="3"/>
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
  </IconBase>);
const IconMicOff = (p) => (<IconBase {...p}>
    <path d="M9 9V6a3 3 0 0 1 6 0v5m0 4a3 3 0 0 1-6 0"/>
    <path d="M5 11a7 7 0 0 0 11.5 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3"/>
    <path d="M3 3l18 18"/>
  </IconBase>);
const IconChat = (p) => (<IconBase {...p}>
    <path d="M4 5h16v11H9l-5 4z"/>
  </IconBase>);
const IconBack = (p) => (<IconBase {...p} strokeWidth={1.9}>
    <path d="M15 5l-7 7 7 7"/>
  </IconBase>);
const ControlBtn = ({ size = 48, tone = 'neutral', active = false, disabled, label, ariaLabel, onClick, children, }) => {
    const bg = tone === 'danger' ? HP_CALL.end :
        tone === 'start' ? HP_CALL.stateSpeaking :
            tone === 'accent' ? HP_CALL.accent :
                active ? 'rgba(255,255,255,0.92)' : HP_CALL.surface2;
    const fg = tone === 'danger' || tone === 'start' ? '#ffffff' :
        tone === 'accent' ? '#052c33' :
            active ? '#0b0b0c' : HP_CALL.text;
    const glow = tone === 'danger' ? 'rgba(239, 68, 68, 0.45)' :
        tone === 'start' ? 'rgba(16, 185, 129, 0.45)' :
            tone === 'accent' ? 'rgba(34, 211, 238, 0.4)' :
                'rgba(0, 0, 0, 0.3)';
    const border = tone === 'neutral' && !active ? `1px solid ${HP_CALL.border}` : 'none';
    return (<div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
            opacity: disabled ? 0.45 : 1,
        }}>
      <button type="button" onClick={onClick} disabled={disabled} aria-label={ariaLabel || label || ''} style={{
            width: size, height: size, borderRadius: '50%',
            background: bg, border, color: fg, padding: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: disabled ? 'not-allowed' : 'pointer',
            boxShadow: tone === 'neutral' && !active
                ? 'inset 0 1px 0 rgba(255,255,255,0.04)'
                : `0 8px 22px ${glow}, inset 0 1px 0 rgba(255,255,255,0.12)`,
            transition: 'transform 80ms ease, background 120ms ease, box-shadow 120ms ease',
        }}>
        {children}
      </button>
      {label ? (<span style={{
                fontFamily: HP_CALL.font, fontSize: 11, fontWeight: 500, letterSpacing: 0.2,
                color: HP_CALL.text3, textTransform: 'lowercase',
            }}>{label}</span>) : null}
    </div>);
};
// ── CallAvatar (ported from phone/avatar.jsx) ─────────────────────
const CallAvatar = ({ size = 156, state, imageUrl = null, accentColor = null }) => {
    const stateColor = hpCallStateColor(state);
    const breathes = state === 'listening' ||
        state === 'connecting' ||
        state === 'speaking' ||
        state === 'dialing';
    const showPulseRings = state === 'dialing';
    const haloOuter = size + 28;
    // seed + hue derivation now live inside the Aura primitive
    // (hashHue + moodOffset). This component only owns the halo +
    // ring decorations that depend on CallState.
    return (<div style={{
            position: 'relative', width: haloOuter, height: haloOuter,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
      {/* Expanding pulse rings — only while dialing. Three rings on
            staggered delays so the modal reads as "ringing", not just
            "spinning up". */}
      {showPulseRings && [0, 1, 2].map(i => (<div key={i} aria-hidden="true" style={{
                position: 'absolute', inset: 0, borderRadius: '50%',
                border: `1.5px solid ${stateColor}`,
                // Split to longhand so per-ring animationDelay doesn't race
                // the shorthand reset — React warns when both are set
                // (mixing shorthand + longhand produces inconsistent results
                // across browsers).
                animationName: 'hp-call-pulse-ring',
                animationDuration: '1600ms',
                animationTimingFunction: 'ease-out',
                animationIterationCount: 'infinite',
                animationDelay: `${i * 420}ms`,
                opacity: 0,
            }}/>))}
      <div style={{
            position: 'absolute', inset: 0, borderRadius: '50%',
            background: `radial-gradient(circle, ${stateColor}55 0%, transparent 68%)`,
            filter: 'blur(14px)',
            opacity: breathes ? 0.8 : 0.35,
            animation: breathes ? 'hp-halo-breathe 2s ease-in-out infinite' : 'none',
        }}/>
      <div style={{
            position: 'absolute', width: size + 10, height: size + 10,
            borderRadius: '50%',
            border: `2px solid ${stateColor}`,
            opacity: state === 'ended' || state === 'muted' ? 0.25 : 0.92,
        }}/>
      <div style={{
            // ``state === 'ended'`` filter stays on this wrapper so
            // the Aura primitive stays state-agnostic while the
            // overlay still gets a visible "call's over" cue.
            filter: state === 'ended'
                ? 'grayscale(0.6) brightness(0.7)'
                : 'none',
            borderRadius: '50%',
        }}>
        <Aura seed={imageUrl || accentColor || 'homepilot'} size={size} photoUrl={imageUrl} 
    // Hue-drift polish is the only thing the Aura primitive
    // animates internally. We disable it here — the overlay
    // already owns the halo breath + dialing rings, and the
    // combined motion was too busy on the call surface.
    animated={false}/>
      </div>
    </div>);
};
const CallModal = ({ state, personaName, imageUrl = null, accentColor = null, durationSec, onEnd, onToggleMute, onMinimize, onSwitchToChat, intensityRef, }) => {
    const stateColor = hpCallStateColor(state);
    const stateLabel = hpCallStateLabel(state, personaName);
    const mm = Math.floor(durationSec / 60).toString().padStart(2, '0');
    const ss = (durationSec % 60).toString().padStart(2, '0');
    const preConnect = state === 'dialing' || state === 'connecting';
    const timer = preConnect ? '—:—' : `${mm}:${ss}`;
    return (<div style={{
            width: 'min(420px, 92vw)',
            padding: '18px 22px 26px',
            borderRadius: 24,
            background: HP_CALL.surface,
            border: `1px solid ${HP_CALL.border}`,
            boxShadow: '0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04)',
            position: 'relative', overflow: 'hidden',
            fontFamily: HP_CALL.font, color: HP_CALL.text,
            animation: 'hp-call-in 180ms ease-out',
        }}>
      <div style={{
            position: 'absolute', inset: '-40% -10% auto -10%', height: '60%',
            background: `radial-gradient(ellipse at 50% 100%, ${stateColor}26 0%, transparent 65%)`,
            pointerEvents: 'none', opacity: state === 'muted' ? 0.1 : 0.35,
        }}/>

      {/* Header row */}
      <div style={{
            position: 'relative', zIndex: 2,
            display: 'flex', alignItems: 'center',
            height: 32, marginBottom: 10,
        }}>
        <button type="button" onClick={onMinimize} aria-label="Minimize call" style={{
            width: 32, height: 32, borderRadius: 10, padding: 0,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: HP_CALL.text2,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <IconBack size={18} color={HP_CALL.text2}/>
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
        <CallAvatar size={156} state={state} imageUrl={imageUrl} accentColor={accentColor}/>
      </div>

      {/* State label + waveform/dots */}
      <div style={{
            position: 'relative', zIndex: 2,
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            gap: 10, marginBottom: 22, minHeight: 52,
        }}>
        {preConnect ? (<div style={{ display: 'flex', gap: 5 }}>
            {[0, 1, 2].map(i => (<div key={i} style={{
                    width: 5, height: 5, borderRadius: '50%',
                    background: HP_CALL.text,
                    opacity: 0.35 + i * 0.2,
                    // Longhand — keeps per-dot animationDelay from being
                    // reset by the shorthand during React rerenders.
                    animationName: 'hp-dot-pulse',
                    animationDuration: state === 'dialing' ? '1.2s' : '0.8s',
                    animationTimingFunction: 'ease-in-out',
                    animationIterationCount: 'infinite',
                    animationDelay: `${i * 0.12}s`,
                }}/>))}
          </div>) : (<Waveform bars={26} height={24} mode={waveformModeFromCallState(state)} seed={personaName} intensityRef={intensityRef}/>)}
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
        <ControlBtn size={56} active={state === 'muted'} ariaLabel={state === 'muted' ? 'Unmute microphone' : 'Mute microphone'} onClick={onToggleMute} disabled={state === 'dialing' || state === 'connecting' || state === 'ended'}>
          {state === 'muted'
            ? <IconMicOff size={22} color="#0b0b0c"/>
            : <IconMic size={22}/>}
        </ControlBtn>

        <ControlBtn size={72} tone="danger" ariaLabel="End call" onClick={onEnd}>
          <IconPhoneEnd size={26} color="#ffffff"/>
        </ControlBtn>

        <ControlBtn size={56} ariaLabel="Switch to text chat" onClick={onSwitchToChat} disabled={!onSwitchToChat || state === 'dialing' || state === 'connecting' || state === 'ended'}>
          <IconChat size={22}/>
        </ControlBtn>
      </div>
    </div>);
};
// Outer shell — renders nothing when closed so the voice hook inside
// CallOverlayInner only mounts during an active call. This matters: the
// voice controller requests mic permission + starts the VAD as soon as
// it mounts. Keeping it gated behind `open` means the mic is only
// touched while the user is in a call.
export default function CallOverlay(props) {
    if (!props.open)
        return null;
    return <CallOverlayInner {...props}/>;
}
function CallOverlayInner({ onClose, personaName = 'Assistant', avatarUrl = null, accentColor = null, onMinimize, onSwitchToChat, skipDialing = false, onEnded, onSendText, backend, messages, }) {
    const initial = skipDialing ? 'connecting' : 'dialing';
    const [state, setState] = useState(initial);
    const [muted, setMuted] = useState(false);
    const [durationSec, setDurationSec] = useState(0);
    // Staged lifecycle on mount:
    //   dialing (DIAL_MS) → connecting (CONNECT_MS) → listening
    //   (or: connecting → listening when skipDialing).
    useEffect(() => {
        const timers = [];
        if (!skipDialing) {
            timers.push(window.setTimeout(() => {
                setState(s => (s === 'dialing' ? 'connecting' : s));
            }, DIAL_MS));
        }
        timers.push(window.setTimeout(() => {
            setState(s => (s === 'connecting' || s === 'dialing') ? 'listening' : s);
        }, (skipDialing ? 0 : DIAL_MS) + CONNECT_MS));
        return () => { timers.forEach(t => window.clearTimeout(t)); };
    }, [skipDialing]);
    // Live timer during active call (dialing + connecting don't count).
    useEffect(() => {
        if (state === 'dialing' || state === 'connecting' || state === 'ended')
            return;
        const iv = window.setInterval(() => setDurationSec((n) => n + 1), 1000);
        return () => window.clearInterval(iv);
    }, [state]);
    // Ringback tone — PSTN-standard two-frequency synthesis via
    // WebAudio. US telephony uses 440 Hz + 480 Hz played together, 2 s
    // on / 4 s off. We play one full on-phase (2 s) during dialing so
    // the user hears a real phone-style ring before pickup. Nothing
    // plays during connecting or live — a phone that keeps ringing
    // after pickup is a broken phone.
    useEffect(() => {
        if (state !== 'dialing')
            return;
        const AC = window.AudioContext ||
            window.webkitAudioContext;
        if (!AC)
            return;
        let ctx = null;
        try {
            ctx = new AC();
        }
        catch {
            return;
        }
        const start = ctx.currentTime + 0.03;
        const durationSec = 2.0; // "on" portion of the 2-on-4-off cadence
        const peakGain = 0.07; // loud enough to be heard, soft enough to sit
        // under the persona's TTS once it lands
        // 440 Hz + 480 Hz fundamentals — the exact CCITT-spec recipe for
        // "ringing signal, North American" (Precise Tone Plan).
        const freqs = [440, 480];
        const oscs = [];
        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(peakGain, start + 0.08);
        gain.gain.setValueAtTime(peakGain, start + durationSec - 0.2);
        gain.gain.linearRampToValueAtTime(0, start + durationSec);
        gain.connect(ctx.destination);
        for (const f of freqs) {
            const o = ctx.createOscillator();
            o.type = 'sine';
            o.frequency.setValueAtTime(f, start);
            o.connect(gain);
            o.start(start);
            o.stop(start + durationSec + 0.05);
            oscs.push(o);
        }
        return () => {
            for (const o of oscs) {
                try {
                    o.stop();
                }
                catch { /* ignore */ }
            }
            try {
                ctx?.close();
            }
            catch { /* ignore */ }
        };
    }, [state]);
    // End-call chime — plays once on ``dialing/connecting/listening/…
    // → ended`` transition. Matches the WhatsApp / FaceTime / Slack
    // Huddle convention: two-tone descending sine (perfect fifth down,
    // 660 → 440 Hz), short (~400 ms), quiet (peak gain 0.15), soft
    // attack + exponential-ish release so there's no click. The second
    // tone overlaps the first by 50 ms for smoothness. Fires inside
    // the END_FADE_MS window so the audio "goodbye" lands with the
    // visual fade — matches every industry example.
    //
    // Same WebAudio pattern as the ringback above so behaviour across
    // browsers is identical. Muted state suppresses the tone — the
    // user already signalled "quiet please".
    useEffect(() => {
        if (state !== 'ended')
            return;
        if (muted)
            return;
        const AC = window.AudioContext ||
            window.webkitAudioContext;
        if (!AC)
            return;
        let ctx = null;
        try {
            ctx = new AC();
        }
        catch {
            return;
        }
        const t0 = ctx.currentTime + 0.02;
        const peakGain = 0.15;
        const attack = 0.02; // 20 ms — no click
        const release = 0.08; // 80 ms — gentle tail
        // Tone 1 — 660 Hz for 180 ms
        const t1Start = t0;
        const t1Dur = 0.18;
        // Tone 2 — 440 Hz, overlaps tone 1 by 50 ms, runs 220 ms
        const t2Start = t0 + 0.13;
        const t2Dur = 0.22;
        const makeTone = (freq, startAt, durSec) => {
            const osc = ctx.createOscillator();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(freq, startAt);
            const gain = ctx.createGain();
            gain.gain.setValueAtTime(0, startAt);
            gain.gain.linearRampToValueAtTime(peakGain, startAt + attack);
            gain.gain.setValueAtTime(peakGain, startAt + durSec - release);
            gain.gain.linearRampToValueAtTime(0, startAt + durSec);
            osc.connect(gain).connect(ctx.destination);
            osc.start(startAt);
            osc.stop(startAt + durSec + 0.05);
            return osc;
        };
        const oscs = [
            makeTone(660, t1Start, t1Dur),
            makeTone(440, t2Start, t2Dur),
        ];
        const totalDuration = (t2Start - t0) + t2Dur + 0.05;
        // Close the context after the tones finish so we don't leave a
        // live audio node dangling. The overlay unmounts ~END_FADE_MS
        // after state='ended' anyway, but being explicit is cheap.
        const closeTimer = window.setTimeout(() => {
            try {
                ctx?.close();
            }
            catch { /* ignore */ }
        }, Math.ceil(totalDuration * 1000) + 50);
        return () => {
            window.clearTimeout(closeTimer);
            for (const o of oscs) {
                try {
                    o.stop();
                }
                catch { /* ignore */ }
            }
            try {
                ctx?.close();
            }
            catch { /* ignore */ }
        };
    }, [state, muted]);
    const handleEnd = useCallback(() => {
        setState('ended');
        // If the backend session is live, send a graceful call.control
        // 'end' envelope so the server-side ledger closes cleanly.
        if (useBackendRef.current) {
            try {
                sessionRef.current.end();
            }
            catch { /* ignore */ }
        }
        // Capture the live-phase duration NOW — durationSec is frozen at
        // the last tick because the interval effect tears down on
        // state==='ended'. Close after a short fade so the backdrop +
        // modal get a chance to animate out.
        const endedWith = durationSec;
        window.setTimeout(() => {
            if (onEnded)
                onEnded(endedWith);
            onClose();
        }, END_FADE_MS);
    }, [onClose, onEnded, durationSec]);
    // Esc ends.
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape')
            handleEnd(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [handleEnd]);
    // ── Backend voice_call session (preferred transport) ───────────
    // When a `backend` prop is supplied we attempt the dedicated
    // voice_call WebSocket. If the backend responds 404/501 we stay
    // in 'unavailable' and the chat-REST fallback takes over below.
    const session = useCallSession({
        enabled: !!backend,
        backendUrl: backend?.backendUrl ?? '',
        authToken: backend?.authToken ?? null,
        request: useMemo(() => ({
            conversation_id: backend?.conversationId ?? null,
            persona_id: backend?.personaId ?? null,
            entry_mode: 'call',
            // Declare Phase 2/3 client capability. Server replies with
            // its own capability advertisement; effective mode is the
            // intersection (useCallSession reads capabilities from the
            // session-create response).
            device_info: {
                tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
                platform: navigator.platform,
                streaming: true,
                barge_in: true,
            },
        }), [backend?.conversationId, backend?.personaId]),
    });
    const useBackend = !!backend &&
        session.status !== 'unavailable' &&
        session.status !== 'error';
    // ── "Listen first" gate — opener-TTS is playing ───────────────
    // When the backend emits the curated opening greeting as a
    // transcript.final right after call.state live, the client's
    // microphone must stay CLOSED until the greeting has finished
    // speaking. Otherwise the user's natural "hello?" mid-greeting
    // triggers a barge-in and cuts the persona off — the opposite
    // of the "AI answers first, user listens" product spec.
    //
    // openerDoneRef is a one-shot — once the first assistant
    // utterance has finished, subsequent utterances (responses to
    // user turns) do NOT relock the mic; the user can barge-in on
    // those freely, which is the correct UX.
    const [openerPlaying, setOpenerPlaying] = useState(false);
    // ``connected`` is a pure derivation from ``state``; declared early
    // so effects that fire before the setHandsFree gate (fallback opener
    // below) can reference it without a forward-ref.
    const connected = state !== 'dialing' && state !== 'connecting' && state !== 'ended';
    const openerDoneRef = useRef(false);
    useEffect(() => {
        if (session.status === 'creating') {
            openerDoneRef.current = false;
            setOpenerPlaying(false);
        }
    }, [session.status]);
    // ── Real voice pipeline ────────────────────────────────────────
    // STT capture → preferred transport. If the backend session is
    // live we route transcripts through the voice_call WS; otherwise
    // we fall back to onSendText (regular chat REST) so the overlay
    // still works when VOICE_CALL_ENABLED is off server-side.
    const onSendTextRef = useRef(onSendText);
    useEffect(() => { onSendTextRef.current = onSendText; }, [onSendText]);
    const sessionRef = useRef(session);
    useEffect(() => { sessionRef.current = session; }, [session]);
    const useBackendRef = useRef(useBackend);
    useEffect(() => { useBackendRef.current = useBackend; }, [useBackend]);
    const voice = useVoiceController((text) => {
        clog({
            e: 'turn',
            action: 'user_out',
            route: useBackendRef.current ? 'ws' : 'chat_rest',
        });
        if (useBackendRef.current) {
            sessionRef.current.sendTranscript(text);
        }
        else {
            onSendTextRef.current?.(text);
        }
    });
    const turnLockRef = useRef('idle');
    const turnUnlockTimerRef = useRef(null);
    const fullDuplexEnabledRef = useRef(isCallFullDuplexEnabled());
    const setTurnLock = useCallback((next, trigger) => {
        if (!fullDuplexEnabledRef.current)
            return;
        const prev = turnLockRef.current;
        if (prev === next)
            return;
        turnLockRef.current = next;
        voice.setListeningSuppressed(next === 'ai', `turn_lock:${trigger}`);
        clog({ e: 'state', from: prev, to: next, trigger });
    }, [voice]);
    const releaseAiTurnWithMargin = useCallback((trigger) => {
        if (turnUnlockTimerRef.current) {
            window.clearTimeout(turnUnlockTimerRef.current);
            turnUnlockTimerRef.current = null;
        }
        turnUnlockTimerRef.current = window.setTimeout(() => {
            setTurnLock('idle', `${trigger}:margin_release`);
            turnUnlockTimerRef.current = null;
        }, 300);
    }, [setTurnLock]);
    useEffect(() => {
        return () => {
            if (turnUnlockTimerRef.current) {
                window.clearTimeout(turnUnlockTimerRef.current);
                turnUnlockTimerRef.current = null;
            }
        };
    }, []);
    const speakText = useCallback((text) => {
        if (!text || !text.trim())
            return;
        setTurnLock('ai', 'speak:start');
        const isOpener = !openerDoneRef.current;
        if (isOpener)
            setOpenerPlaying(true);
        const markDone = () => {
            openerDoneRef.current = true;
            setOpenerPlaying(false);
            // 300 ms margin before we flip the lock back to 'idle'. Echo
            // tail can linger after TTS says "ended"; releasing immediately
            // would let the mic re-open while our own voice is still in
            // the air.
            releaseAiTurnWithMargin('speak:end');
        };
        // Length-based estimate for the SpeechService path (the shim
        // doesn't expose onend). ~12 chars/sec; floor 1.5 s so "Yes?"
        // still gives the user a beat; ceiling 8 s so a runaway
        // greeting can't lock the mic indefinitely.
        const estimateSpeechMs = (t) => Math.max(1500, Math.min(8000, t.length * 80));
        try {
            // Prefer the owned TTS path when full-duplex is on. speakOwned
            // handles both the window.SpeechService route AND the
            // cross-source dedupe (see call/log.ts). Returns true iff this
            // caller owns the utterance; false means another source
            // (App-level TTS) was mid-speak — we fall through to the legacy
            // speechSynthesis path unchanged so the overlay isn't silent.
            if (fullDuplexEnabledRef.current) {
                const spoke = speakOwned('overlay', text, {
                    onEnd: markDone,
                    onError: () => markDone(),
                });
                if (spoke) {
                    if (isOpener)
                        window.setTimeout(markDone, estimateSpeechMs(text));
                    return;
                }
            }
            else {
                const w = window;
                if (w.SpeechService?.speak) {
                    w.SpeechService.speak(text);
                    if (isOpener)
                        window.setTimeout(markDone, estimateSpeechMs(text));
                    return;
                }
            }
            if ('speechSynthesis' in window) {
                const utt = new SpeechSynthesisUtterance(text);
                if (isOpener) {
                    utt.onend = markDone;
                    utt.onerror = markDone;
                    window.setTimeout(markDone, estimateSpeechMs(text));
                }
                window.speechSynthesis.speak(utt);
                return;
            }
            if (isOpener)
                markDone();
        }
        catch {
            if (isOpener)
                markDone();
        }
    }, [setTurnLock, releaseAiTurnWithMargin]);
    // WS path — speak every assistant transcript.final (the opening
    // greeting from ws.py, and in unary mode every reply). In
    // streaming mode, per-token partials go through streamTts below
    // and THIS path fires only for transcript.final emitted outside
    // a streamed turn — e.g. the opener itself.
    useEffect(() => {
        if (!useBackend)
            return;
        const unsub = session.onAssistantTranscript((p) => {
            clog({ e: 'turn', action: 'assistant_in', route: 'ws' });
            speakText(p.text);
        });
        return unsub;
    }, [useBackend, session, speakText]);
    // ── Fallback mode (VOICE_CALL_ENABLED=false on backend) ───────
    // When the backend voice_call route isn't mounted, the session
    // POST 404s, useBackend stays false, and the STT pipeline routes
    // through the regular chat-REST path (onSendText above). That
    // works for text round-tripping — but without the hooks below,
    // the assistant's replies land in chatMessages and are never
    // spoken, so the user hears nothing.
    //
    // These two effects close that gap so the overlay is functional
    // even with the WS disabled:
    //   (a) a synthetic opener fires when the call connects, so the
    //       AI still "answers first"
    //   (b) every new assistant message arriving in ``messages``
    //       during the call is spoken via the same TTS path the WS
    //       reply path uses
    // (a) Fallback opener — once per session, when the line connects
    // and we're running fallback mode, pick a short greeting and
    // speak it. The greeting is marked as opener via speakText's
    // first-utterance heuristic, so the mic gate stays closed
    // exactly like the WS path.
    const fallbackOpeners = useMemo(() => [
        'Hello?',
        'Yes?',
        `Hi, this is ${personaName}.`,
        `${personaName} speaking.`,
        `Hey — ${personaName}.`,
        `Hi, ${personaName} here.`,
    ], [personaName]);
    const fallbackOpenerFiredRef = useRef(false);
    useEffect(() => {
        if (useBackend)
            return;
        if (!connected)
            return;
        if (fallbackOpenerFiredRef.current)
            return;
        fallbackOpenerFiredRef.current = true;
        const g = fallbackOpeners[Math.floor(Math.random() * fallbackOpeners.length)];
        speakText(g);
    }, [useBackend, connected, fallbackOpeners, speakText]);
    // (b) Ongoing assistant replies in fallback mode are now spoken
    // by the App-level TTS effect (App.tsx — gated on callOpen). That
    // pipeline already handles stripMarkdownForSpeech + per-message
    // dedupe via lastSpokenMessageIdRef, so we don't duplicate it
    // here. The fallback OPENER above stays — it's synthesized in
    // the overlay and never enters chatMessages, so the App-level
    // effect can't produce it.
    //
    // ``messages`` prop is still accepted for future use (mid-call
    // transcript viewer, etc.) but intentionally unused here — no
    // TTS side-effect reads it.
    // ── Phase 2: streaming TTS pipeline ───────────────────────────
    // Holds one streamTts instance per mounted overlay. Stopped on
    // unmount so a re-entry creates a fresh engine.
    const ttsRef = useRef(null);
    useEffect(() => {
        if (!useBackend || !session.streamingNegotiated) {
            ttsRef.current = null;
            return;
        }
        const tts = createStreamingTts();
        ttsRef.current = tts;
        return () => {
            try {
                tts.stop();
            }
            catch { /* ignore */ }
            ttsRef.current = null;
        };
    }, [useBackend, session.streamingNegotiated]);
    // Track the currently-streaming turn_id so the barge-in path can
    // address the right turn without racing a new one.
    const currentTurnIdRef = useRef(null);
    // Partial deltas → streamTts.appendDelta. Each delta triggers
    // sentence-boundary flushing inside the TTS engine; callers don't
    // see the buffering.
    useEffect(() => {
        if (!useBackend || !session.streamingNegotiated)
            return;
        return session.onAssistantPartial((p) => {
            currentTurnIdRef.current = p.turn_id;
            ttsRef.current?.appendDelta(p.delta);
        });
    }, [useBackend, session]);
    // Turn end → flush residual buffer + clear the active turn id.
    useEffect(() => {
        if (!useBackend || !session.streamingNegotiated)
            return;
        return session.onAssistantTurnEnd((p) => {
            if (p.reason === 'cancelled' || p.reason === 'error') {
                ttsRef.current?.stop();
            }
            else {
                ttsRef.current?.flush();
            }
            if (currentTurnIdRef.current === p.turn_id) {
                currentTurnIdRef.current = null;
            }
        });
    }, [useBackend, session]);
    // Server-initiated cancel (barge-in ack) → stop TTS immediately.
    // Must land inside ~50 ms of receipt (§ 5.3 contract).
    useEffect(() => {
        if (!useBackend || !session.streamingNegotiated)
            return;
        return session.onAssistantCancel((_p) => {
            ttsRef.current?.stop();
        });
    }, [useBackend, session]);
    // ── Phase 3: barge-in VAD tap ─────────────────────────────────
    // Audio level mirror — useVoiceController returns fresh values
    // every render; we stash the latest into a ref so the rAF loop
    // inside useBargeInDetector always sees the current value.
    const voiceLevelRef = useRef(0);
    useEffect(() => {
        voiceLevelRef.current = voice.audioLevel;
    }, [voice.audioLevel]);
    // Re-evaluated each render; the detector's rAF loop reads its own
    // refs so identity changes don't thrash.
    const bargeInEnabled = useBackend &&
        session.bargeInNegotiated &&
        (ttsRef.current?.isSpeaking ?? false);
    useBargeInDetector({
        audioLevelRef: voiceLevelRef,
        enabled: bargeInEnabled,
        onBargeIn: () => {
            const tid = currentTurnIdRef.current;
            clog({ e: 'turn', action: 'barge_in', route: 'ws' });
            ttsRef.current?.stop();
            if (tid)
                session.sendBargeIn(tid);
        },
    });
    // Call-center-style auto-greeting — the moment the backend session
    // goes live, prompt the persona to answer first (the way a real
    // person picks up the phone). We send a short synthetic transcript
    // the backend's persona_call phase machine will treat as turn 0 of
    // the opening sequence — it responds with a contextual "hello?" /
    // "hey, what's up?" in the persona's own voice.
    //
    // This is a one-shot per call session. `greetedRef` guards against
    // reconnect storms triggering a second "hello".
    const greetedRef = useRef(false);
    useEffect(() => {
        if (!useBackend)
            return;
        if (session.callState !== 'live')
            return;
        if (greetedRef.current)
            return;
        greetedRef.current = true;
        // One very short open-channel ping. persona_call reads this as the
        // caller-initiated summons in the Schegloff opening structure and
        // the persona answers.
        session.sendTranscript('[phone-call-open]');
    }, [useBackend, session]);
    // Reset the greet guard when a fresh session is (re)created.
    useEffect(() => {
        if (session.status === 'creating')
            greetedRef.current = false;
    }, [session.status]);
    // Backchannel + filler events are short, low-volume TTS clips.
    // We route them through the same speak path; they're short enough
    // (one token) that interrupting a reply mid-stream is fine.
    useEffect(() => {
        if (!useBackend)
            return;
        const unsub1 = session.onAssistantBackchannel((p) => {
            try {
                window.speechSynthesis?.speak?.(new SpeechSynthesisUtterance(p.token));
            }
            catch { /* ignore */ }
        });
        const unsub2 = session.onAssistantFiller((p) => {
            try {
                window.speechSynthesis?.speak?.(new SpeechSynthesisUtterance(p.token));
            }
            catch { /* ignore */ }
        });
        return () => { unsub1(); unsub2(); };
    }, [useBackend, session]);
    // Enter hands-free once the line is "connected" AND the opener
    // has finished speaking. The second gate is the "listen first"
    // rule — the AI speaks its greeting and the user hears it out
    // before the mic opens; otherwise a natural early "hello?" trips
    // the barge-in detector and cuts the persona off mid-greeting.
    // ``connected`` is declared earlier (near state).
    //
    // This effect intentionally has NO cleanup that toggles handsFree —
    // the original cleanup raced against `openerPlaying` transitions
    // and re-render-driven re-runs (voice + setTurnLock change identity
    // on every render), which flipped handsFree OFF mid-call and left
    // state on OFF right when the user started speaking. The STT path
    // then dropped the VAD speech_start because state !== IDLE. Tear-
    // down lives in the dedicated unmount effect below.
    const voiceHandleRef = useRef(voice);
    useEffect(() => { voiceHandleRef.current = voice; }, [voice]);
    const setTurnLockRef = useRef(setTurnLock);
    useEffect(() => { setTurnLockRef.current = setTurnLock; }, [setTurnLock]);
    useEffect(() => {
        if (!connected)
            return;
        if (openerPlaying)
            return;
        setTurnLockRef.current('idle', 'connected_open_mic');
        voiceHandleRef.current.setHandsFree(true);
    }, [connected, openerPlaying]);
    // Unmount-only cleanup. Guarantees the mic is released and the
    // turn-lock is reset when the overlay actually tears down (call
    // ended, user navigated away), without coupling that teardown to
    // the normal-effect re-run cycle above.
    useEffect(() => {
        return () => {
            try {
                voiceHandleRef.current.setHandsFree(false);
            }
            catch { /* ignore */ }
            try {
                setTurnLockRef.current('idle', 'cleanup');
            }
            catch { /* ignore */ }
        };
    }, []);
    // Mirror the voice-controller's machine onto our UI state so the
    // halo + waveform + label actually reflect what's happening:
    //   LISTENING     → 'listening'
    //   THINKING      → 'thinking'
    //   SPEAKING      → 'speaking'
    //   IDLE          → 'listening' (ready, nothing to say yet)
    //   OFF / muted   → preserved
    useEffect(() => {
        if (!connected)
            return;
        if (muted)
            return;
        const mapped = mapVoiceState(voice.state);
        if (!mapped)
            return;
        setState(prev => {
            if (prev === 'ended' || prev === 'muted')
                return prev;
            return mapped;
        });
    }, [voice.state, connected, muted]);
    // Mirror the voice-controller's LISTENING / THINKING onto the
    // turn-lock 'user' slot. The AI owns 'ai' (see speakText); VAD
    // drives 'user' only when the AI isn't already speaking. This is
    // the industry-standard "who has the floor" gate — with it, the
    // AI's TTS bleed through the speaker can't trip a false user turn
    // (the root cause of the "AI says yes, hears itself, stops" bug).
    useEffect(() => {
        if (!fullDuplexEnabledRef.current)
            return;
        if (!connected)
            return;
        if (muted)
            return;
        if (voice.state === 'LISTENING' && turnLockRef.current === 'idle') {
            clog({ e: 'vad', action: 'speech_start', state: voice.state });
            setTurnLock('user', 'voice_listening');
        }
        else if (voice.state === 'THINKING' && turnLockRef.current === 'user') {
            clog({ e: 'vad', action: 'speech_end', state: voice.state });
            setTurnLock('idle', 'voice_thinking');
        }
    }, [voice.state, connected, muted, setTurnLock]);
    // While the opener TTS is playing, the UI label must read
    // 'speaking' — the persona is literally talking. Default state
    // transitions would land on 'listening' (post-connect default)
    // which is a lie: audio is going OUT of the speaker, not coming
    // IN to the mic. The mic is still closed (see the openerPlaying
    // gate on setHandsFree above), so voice.state stays OFF during
    // this window and the mirror effect above doesn't override us.
    useEffect(() => {
        if (!openerPlaying)
            return;
        setState(prev => (prev === 'ended' || prev === 'muted') ? prev : 'speaking');
    }, [openerPlaying]);
    // ── Live waveform intensity (0..1) ─────────────────────────────
    // One rAF loop per state-group writes to a ref that CallWaveform
    // reads directly (no React re-renders). React only sees the state
    // label; the bars themselves are driven straight from the DOM.
    //
    //   listening / muted → voice.audioLevel (real mic RMS)
    //   speaking          → synthesised speech envelope — browser TTS
    //                       audio isn't routable through an AnalyserNode,
    //                       so we generate a natural-sounding envelope
    //                       (sum of 3 sines + a small noise floor). The
    //                       visual cadence matches syllable rate + the
    //                       amplitude range matches what mic analysers
    //                       produce on voiced speech, so the persona's
    //                       bars and the user's bars "look like the
    //                       same kind of thing."
    //   thinking          → slow 0.15..0.25 drift — "processing"
    //   dialing/connecting/ended → 0.05 floor — visible but quiet
    const intensityRef = useRef(0.05);
    const voiceRef = useRef(voice);
    useEffect(() => { voiceRef.current = voice; }, [voice]);
    useEffect(() => {
        let raf = 0;
        const start = performance.now();
        if (state === 'listening' || state === 'muted') {
            const tick = () => {
                // Real mic level. useVoiceController already smooths with
                // an EMA internally; we pass it through unmodified.
                intensityRef.current = muted ? 0 : voiceRef.current.audioLevel;
                raf = requestAnimationFrame(tick);
            };
            raf = requestAnimationFrame(tick);
            return () => cancelAnimationFrame(raf);
        }
        if (state === 'speaking') {
            const tick = () => {
                const t = (performance.now() - start) / 1000;
                // Three sines at the frequencies you'd see in actual
                // voiced speech analysis: ~2 Hz syllable rate, ~5 Hz
                // mid-band, ~10 Hz high-band flutter. A small noise floor
                // breaks the periodicity so bars don't pulse in lockstep.
                const v = 0.45 +
                    Math.sin(t * 2.3) * 0.22 +
                    Math.sin(t * 5.7 + 1.3) * 0.16 +
                    Math.sin(t * 11.1 + 2.7) * 0.09 +
                    (Math.random() - 0.5) * 0.07;
                intensityRef.current = Math.max(0, Math.min(1, v));
                raf = requestAnimationFrame(tick);
            };
            raf = requestAnimationFrame(tick);
            return () => cancelAnimationFrame(raf);
        }
        if (state === 'thinking') {
            const tick = () => {
                const t = (performance.now() - start) / 1000;
                intensityRef.current = 0.18 + Math.sin(t * 1.1) * 0.06;
                raf = requestAnimationFrame(tick);
            };
            raf = requestAnimationFrame(tick);
            return () => cancelAnimationFrame(raf);
        }
        // dialing / connecting / ended → static low floor.
        intensityRef.current = 0.05;
    }, [state, muted]);
    const toggleMute = useCallback(() => {
        setMuted((m) => {
            const next = !m;
            if (next) {
                voice.setHandsFree(false);
                setState('muted');
            }
            else {
                voice.setHandsFree(true);
                setState('listening');
            }
            if (useBackendRef.current) {
                try {
                    sessionRef.current.sendUiState({ muted: next });
                }
                catch { /* ignore */ }
            }
            return next;
        });
    }, [voice]);
    const handleMinimize = useCallback(() => {
        if (onMinimize)
            onMinimize();
        else
            onClose();
    }, [onMinimize, onClose]);
    return (<div role="dialog" aria-modal="true" aria-label={`Call with ${personaName}`} className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0" style={{
            background: HP_CALL.backdrop,
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
            transition: 'opacity 200ms ease',
            opacity: state === 'ended' ? 0 : 1,
        }}/>
      <div className="relative z-10">
        <CallModal state={state} personaName={personaName} imageUrl={avatarUrl} accentColor={accentColor} durationSec={durationSec} onEnd={handleEnd} onToggleMute={toggleMute} onMinimize={handleMinimize} onSwitchToChat={onSwitchToChat} intensityRef={intensityRef}/>
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
        @keyframes hp-call-pulse-ring {
          0%   { transform: scale(1);    opacity: 0.65; }
          80%  { opacity: 0; }
          100% { transform: scale(1.55); opacity: 0; }
        }
        @keyframes hp-call-toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>);
}
// ── Call-ended toast removed ──────────────────────────────────────
// The former CallEndedToast has been retired. The inline
// CallEventRow (rendered directly in the chat stream) now carries
// the post-call record + Resume affordance, so a floating toast
// would be redundant. Kept this comment as a reviewer breadcrumb.
