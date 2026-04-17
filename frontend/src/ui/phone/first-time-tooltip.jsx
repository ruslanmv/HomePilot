// first-time-tooltip.jsx — the "Talk live" hint shown once per user
// when they first visit the Voice page.
//
// Spec-compliant:
//   • Shows 400 ms after Voice page first load.
//   • Auto-dismisses after 4 s or any click.
//   • Stored under the user-scoped key homepilot_voice_call_hint_seen
//     so the hint doesn't replay on account switch AND doesn't leak
//     across users.
//   • Pill floats just below the call button, tail arrow pointing up.
//
// This file draws the static visual only. Timing + dismissal is
// wired in the host component.

function HPCallFirstTimeTooltip({
  visible = true,
  text = 'Talk live',
}) {
  if (!visible) return null;
  return (
    <div style={{
      position: 'relative',
      display: 'inline-flex',
      flexDirection: 'column', alignItems: 'center',
      pointerEvents: 'none',
    }}>
      {/* upward tail — 8 px triangle */}
      <div style={{
        width: 0, height: 0,
        borderLeft: '6px solid transparent',
        borderRight: '6px solid transparent',
        borderBottom: `7px solid ${HP_CALL.start}`,
      }} />
      {/* pill */}
      <div style={{
        padding: '8px 12px',
        borderRadius: 10,
        background: HP_CALL.start,
        color: '#052c21',
        fontFamily: HP_CALL.font,
        fontSize: 12, fontWeight: 600, letterSpacing: 0.1,
        boxShadow: `
          0 6px 14px rgba(16,185,129,0.35),
          0 2px 4px rgba(0,0,0,0.2),
          inset 0 1px 0 rgba(255,255,255,0.25)
        `,
        whiteSpace: 'nowrap',
      }}>{text}</div>
    </div>
  );
}

Object.assign(window, { HPCallFirstTimeTooltip });
