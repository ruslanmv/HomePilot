// call-button.jsx — the emerald phone icon in the Voice page header.
//
// Follows the product spec agreed with you:
//   • Lives top-right on the Voice page header, BEFORE the gear icon.
//   • Diameter 36 px (≈ +15% over the gear's 32 px — asserts primary
//     action without shouting).
//   • Rest state:  emerald-500 fill + white glyph, soft outer halo.
//   • Hover:       emerald-600 fill + halo grows, 120 ms.
//   • Mid-call:    morphs into red-500 end-call button in the SAME
//     pixel position (so the user habit is preserved across states).
//   • After call:  morphs back to rest emerald. No separate end
//     button lives anywhere else.
//
// First-time tooltip ("Talk live") is NOT drawn here — it ships as a
// sibling overlay so the button geometry stays pixel-identical across
// first and subsequent loads.

function HPCallButton({
  state = 'rest',       // 'rest' | 'hover' | 'dialing' | 'inCall' | 'inCallHover'
  size = 36,
}) {
  const isActive = state === 'inCall' || state === 'inCallHover' || state === 'dialing';
  const isHover = state === 'hover' || state === 'inCallHover';

  const bg = (
    isActive
      ? (isHover ? HP_CALL.endHover : HP_CALL.end)
      : (isHover ? HP_CALL.startHover : HP_CALL.start)
  );
  const glyph = isActive || isHover ? '#ffffff' : HP_CALL.startGlyph;
  const haloColor = isActive
    ? (isHover ? 'rgba(239,68,68,0.45)' : 'rgba(239,68,68,0.22)')
    : (isHover ? 'rgba(16,185,129,0.45)' : 'rgba(16,185,129,0.22)');
  const haloThickness = isHover ? 8 : 6;

  // During `dialing` the glyph crossfades (start → end). We cheat the
  // mockup by drawing the start glyph at reduced opacity and the end
  // glyph on top. The real implementation animates both over 300 ms.
  const showEndGlyph = isActive;

  return (
    <div style={{
      position: 'relative',
      width: size, height: size,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {/* Soft outer halo */}
      <div style={{
        position: 'absolute', inset: -haloThickness,
        borderRadius: '50%',
        background: haloColor,
        filter: 'blur(4px)',
        transition: 'inset 120ms ease, background 120ms ease',
      }} />
      {/* Solid disc */}
      <div style={{
        position: 'relative',
        width: size, height: size, borderRadius: '50%',
        background: bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: `
          0 2px 6px rgba(0,0,0,0.3),
          0 6px 14px rgba(0,0,0,0.25),
          inset 0 1px 0 rgba(255,255,255,0.22)
        `,
        transition: 'background 120ms ease, transform 80ms ease',
      }}>
        {showEndGlyph
          ? HPIcon.phoneEnd(Math.round(size * 0.5), glyph)
          : HPIcon.phone(Math.round(size * 0.5), glyph)}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────
// Header mockup — shows the button in its natural context, next to
// the existing gear + pencil icons. Used by the showcase.
// ──────────────────────────────────────────────────────────────────
function HPCallHeaderMock({
  state = 'rest',         // forwarded to HPCallButton
  personaName = 'Darkangel666',
}) {
  const gear = (
    <div style={{
      width: 32, height: 32, borderRadius: 10,
      background: 'rgba(255,255,255,0.04)',
      border: `1px solid ${HP_CALL.border}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: HP_CALL.text2,
    }}>
      {/* simplified gear dot */}
      <div style={{
        width: 14, height: 14, borderRadius: '50%',
        background: HP_CALL.text2, opacity: 0.75,
      }} />
    </div>
  );
  const pencil = (
    <div style={{
      width: 32, height: 32, borderRadius: 10,
      background: 'rgba(255,255,255,0.04)',
      border: `1px solid ${HP_CALL.border}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: HP_CALL.text2,
    }}>
      <div style={{
        width: 14, height: 2, borderRadius: 1,
        background: HP_CALL.text2, opacity: 0.75,
        transform: 'rotate(-45deg)',
      }} />
    </div>
  );
  return (
    <div style={{
      display: 'flex', alignItems: 'center',
      padding: '12px 20px',
      background: HP_CALL.surface,
      borderBottom: `1px solid ${HP_CALL.border}`,
      fontFamily: HP_CALL.font, color: HP_CALL.text,
      gap: 16, minWidth: 520,
    }}>
      {/* left: avatar + persona name */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: 'radial-gradient(circle at 30% 30%, #a78bfa, #6d28d9 70%, #1e1b4b)',
        }} />
        <span style={{ fontSize: 15, fontWeight: 500 }}>{personaName}</span>
      </div>

      <div style={{ flex: 1 }} />

      {/* right cluster: standalone 📞 + grouped ⚙️ ✏️ */}
      {/* 12 px gap between 📞 and the gear/pencil group to visually
          separate a standalone action from utility tools. */}
      <HPCallButton state={state} />
      <div style={{ width: 12 }} />
      <div style={{ display: 'flex', gap: 4 }}>
        {gear}
        {pencil}
      </div>
    </div>
  );
}

Object.assign(window, { HPCallButton, HPCallHeaderMock });
