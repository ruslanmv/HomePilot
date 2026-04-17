// call-pip.jsx — minimized picture-in-picture widget.
//
// When the user minimizes the call modal (taps the back arrow), the
// call doesn't end — it collapses into this small floating dock in
// the bottom-right corner. Clicking it re-opens the full modal; the
// red end-call button is always reachable from here.
//
// Small-surface design principle: the PIP shows only three things —
// identity, state, out. No timer (space), no text toggle (rare use).

function HPCallPip({
  state = 'speaking',        // drives the state halo + waveform color
  personaName = 'Darkangel666',
  imageUrl = null,
  accentColor = null,
  durationSec = 134,         // shown compact ("2:14") to right of the waveform
}) {
  const stateColor = hpCallStateColor(state);
  const mm = Math.floor(durationSec / 60);
  const ss = (durationSec % 60).toString().padStart(2, '0');
  const timerCompact = `${mm}:${ss}`;

  return (
    <div style={{
      width: 280,
      padding: 12,
      borderRadius: 20,
      background: HP_CALL.surface,
      border: `1px solid ${HP_CALL.border}`,
      boxShadow: `
        0 20px 48px rgba(0,0,0,0.55),
        0 0 0 1px rgba(0,0,0,0.3),
        inset 0 1px 0 rgba(255,255,255,0.04)
      `,
      display: 'flex', alignItems: 'center', gap: 12,
      position: 'relative', overflow: 'hidden',
      fontFamily: HP_CALL.font, color: HP_CALL.text,
    }}>
      {/* soft state-colored wash along the left edge to echo the halo */}
      <div style={{
        position: 'absolute', left: -20, top: 0, bottom: 0, width: 80,
        background: `radial-gradient(ellipse at left center, ${stateColor}22 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      {/* mini avatar — smaller halo recipe so the PIP stays compact */}
      <div style={{ position: 'relative', flexShrink: 0, zIndex: 1 }}>
        <HPCallAvatar
          size={40}
          state={state}
          imageUrl={imageUrl}
          accentColor={accentColor}
        />
      </div>

      {/* persona name + waveform + timer */}
      <div style={{ flex: 1, minWidth: 0, zIndex: 1 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: HP_CALL.text,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>{personaName}</div>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: 11, color: HP_CALL.text2,
          fontFamily: HP_CALL.fontTabular,
          fontVariantNumeric: 'tabular-nums',
          marginTop: 2,
        }}>
          <HPCallWaveform
            bars={10} height={12}
            state={state}
            active={state === 'listening' || state === 'speaking'}
            seed={personaName}
          />
          <span>{timerCompact}</span>
        </div>
      </div>

      {/* red hang-up — keeps the affordance reachable while minimized */}
      <div style={{ zIndex: 1, flexShrink: 0 }}>
        <HPControlBtn size={36} tone="danger" ariaLabel="End call">
          {HPIcon.phoneEnd(16, '#ffffff')}
        </HPControlBtn>
      </div>
    </div>
  );
}

Object.assign(window, { HPCallPip });
