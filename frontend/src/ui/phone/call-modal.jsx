// call-modal.jsx — the centered overlay that opens from the header
// Call button (or from holding the mic on the chat page).
//
// Five states the designer must review:
//   connecting / listening / thinking / speaking / muted
//   (ended is intentionally short-lived; we fall back into the chat
//    with a small toast, not a dedicated modal state — this matches
//    FaceTime / Google Meet behavior).
//
// Layout (matches the Darkangel666 reference you shared):
//
//       ← back                                              •
//       ─────────────────────────────────────────────────────
//                        Darkangel666                         ← persona name
//                            0:20                             ← live timer
//                        ┌─────────┐
//                        │ avatar  │                          ← HPCallAvatar
//                        └─────────┘
//                        [ halo color = state ]
//                       ● ● ●   listening                     ← state label
//                   ╭───╮    ╭─╮    ╭───╮
//                   │🎙│    │☎│    │💬│                      ← three controls
//                   ╰───╯    ╰─╯    ╰───╯
//
// Everything here is static and prop-driven — the modal renders a
// specific state frame and never mutates. The real-app version swaps
// the `state` prop based on useVoiceController output.

function HPCallModal({
  state = 'listening',     // 'connecting'|'listening'|'thinking'|'speaking'|'muted'
  personaName = 'Darkangel666',
  imageUrl = null,
  accentColor = null,
  durationSec = 20,        // plain integer seconds; ``formatDuration`` formats mm:ss
  width = 420,
}) {
  const stateColor = hpCallStateColor(state);
  const stateLabel = hpCallStateLabel(state);
  const mm = Math.floor(durationSec / 60).toString().padStart(2, '0');
  const ss = (durationSec % 60).toString().padStart(2, '0');
  const timer = `${mm}:${ss}`;

  return (
    <div style={{
      width,
      padding: '18px 22px 26px',
      borderRadius: 24,
      background: HP_CALL.surface,
      border: `1px solid ${HP_CALL.border}`,
      boxShadow: `
        0 30px 80px rgba(0,0,0,0.55),
        0 0 0 1px rgba(0,0,0,0.4),
        inset 0 1px 0 rgba(255,255,255,0.04)
      `,
      position: 'relative', overflow: 'hidden',
      fontFamily: HP_CALL.font, color: HP_CALL.text,
    }}>
      {/* Subtle state-colored wash at the top to echo the halo */}
      <div style={{
        position: 'absolute', inset: '-40% -10% auto -10%',
        height: '60%',
        background: `radial-gradient(ellipse at 50% 100%, ${stateColor}26 0%, transparent 65%)`,
        pointerEvents: 'none',
        opacity: state === 'muted' ? 0.1 : 0.35,
      }} />

      {/* Header row: back arrow left, minimize right, persona name centered */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', alignItems: 'center',
        height: 32, marginBottom: 10,
      }}>
        <button style={{
          width: 32, height: 32, borderRadius: 10, padding: 0,
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: HP_CALL.text2,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} aria-label="Minimize call">
          {HPIcon.back(18, HP_CALL.text2)}
        </button>
        <div style={{
          position: 'absolute', left: 40, right: 40, textAlign: 'center',
          fontSize: 16, fontWeight: 600, letterSpacing: -0.1,
          color: HP_CALL.text,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          pointerEvents: 'none',
        }}>{personaName}</div>
      </div>

      {/* Live duration (tabular numerals so digits don't reflow) */}
      <div style={{
        position: 'relative', zIndex: 2,
        textAlign: 'center',
        fontSize: 13, color: HP_CALL.text2,
        fontFamily: HP_CALL.fontTabular,
        fontVariantNumeric: 'tabular-nums',
        marginBottom: 18,
      }}>
        {state === 'connecting' ? '—:—' : timer}
      </div>

      {/* Avatar + halo */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', justifyContent: 'center',
        marginBottom: 18,
      }}>
        <HPCallAvatar
          size={156}
          state={state}
          imageUrl={imageUrl}
          accentColor={accentColor}
        />
      </div>

      {/* State label + inline waveform for audio states */}
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
          <HPCallWaveform
            bars={26}
            height={24}
            state={state}
            active={state === 'listening' || state === 'speaking'}
            seed={personaName}
          />
        )}
        <div style={{
          fontSize: 14, fontWeight: 500, letterSpacing: 0.3,
          color: stateColor,
          textTransform: 'lowercase',
        }}>{stateLabel}</div>

        <style>{`
          @keyframes hp-dot-pulse {
            0%, 100% { transform: translateY(0);   opacity: 0.35; }
            50%      { transform: translateY(-3px); opacity: 1; }
          }
        `}</style>
      </div>

      {/* Three-button dock: mic / hang-up / chat */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        gap: 28,
      }}>
        <HPControlBtn
          size={56}
          active={state === 'muted'}
          ariaLabel={state === 'muted' ? 'Unmute microphone' : 'Mute microphone'}
        >
          {state === 'muted'
            ? HPIcon.micOff(22, '#0b0b0c')
            : HPIcon.mic(22)}
        </HPControlBtn>

        <HPControlBtn size={72} tone="danger" ariaLabel="End call">
          {HPIcon.phoneEnd(26, '#ffffff')}
        </HPControlBtn>

        <HPControlBtn size={56} ariaLabel="Switch to text chat">
          {HPIcon.chat(22)}
        </HPControlBtn>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────
// Full-screen "presentation" variant — the same component rendered
// over a blurred backdrop, the way it would actually overlay the app.
// Handy for screenshots of the whole screen, not just the card.
// ──────────────────────────────────────────────────────────────────
function HPCallModalPresentation({ width = 760, height = 480, ...modalProps }) {
  return (
    <div style={{
      width, height, position: 'relative', overflow: 'hidden',
      borderRadius: 14,
      background: `
        radial-gradient(ellipse at 30% 20%, rgba(34,211,238,0.08) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 70%, rgba(167,139,250,0.06) 0%, transparent 45%),
        #050506
      `,
    }}>
      {/* simulated chat behind (blurred, low-opacity) */}
      <div style={{
        position: 'absolute', inset: 0,
        background: `
          linear-gradient(to bottom, transparent 0%, rgba(5,5,6,0.85) 100%),
          repeating-linear-gradient(180deg,
            rgba(255,255,255,0.02) 0 1px,
            transparent 1px 24px
          )
        `,
        filter: 'blur(2px)', opacity: 0.7,
      }} />
      {/* backdrop dim */}
      <div style={{
        position: 'absolute', inset: 0,
        background: HP_CALL.backdrop,
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
      }} />
      {/* modal itself — centered */}
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <HPCallModal {...modalProps} />
      </div>
    </div>
  );
}

Object.assign(window, { HPCallModal, HPCallModalPresentation });
