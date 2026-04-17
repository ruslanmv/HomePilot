// avatar.jsx — persona avatar with state-aware halo ring.
//
// Visual contract:
//   • Inner: 128–176 px circle of persona art (any <img> URL, or an
//     aura placeholder for personas without a custom image).
//   • Middle: 2 px solid ring in the current STATE color (cyan /
//     violet / emerald / red / neutral).
//   • Outer: 12–24 px radial glow in the same color, low alpha.
//   • Connecting / listening / speaking: halo breathes (2 s ease-in-out).
//   • Muted / ended: halo static, neutral.
//
// The ring color is the only thing that changes between states — the
// avatar image itself is untouched. This keeps the persona identity
// stable while the halo communicates system state.

function HPCallAvatar({
  size = 160,
  state = 'listening',
  imageUrl = null,         // persona image. Null → neutral gradient orb.
  accentColor = null,      // per-persona tint for the *idle* aura (not the state halo)
}) {
  const stateColor = hpCallStateColor(state);
  const breathes = state === 'listening' || state === 'connecting' || state === 'speaking';
  const avatarSize = size;
  const haloOuterSize = size + 28;  // 14 px halo on each side

  // Seeded fallback aura gradient (for personas without an image).
  const seed = (imageUrl || accentColor || 'homepilot').toString();
  const hue = [...seed].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;

  return (
    <div style={{
      position: 'relative',
      width: haloOuterSize, height: haloOuterSize,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {/* Outer glow — radial blur in the state color */}
      <div style={{
        position: 'absolute', inset: 0, borderRadius: '50%',
        background: `radial-gradient(circle, ${stateColor}55 0%, transparent 68%)`,
        filter: 'blur(14px)',
        opacity: breathes ? 0.8 : 0.35,
        animation: breathes ? 'hp-halo-breathe 2s ease-in-out infinite' : 'none',
      }} />

      {/* Mid ring — crisp 2 px state color */}
      <div style={{
        position: 'absolute', width: avatarSize + 10, height: avatarSize + 10,
        borderRadius: '50%',
        border: `2px solid ${stateColor}`,
        opacity: state === 'ended' || state === 'muted' ? 0.25 : 0.92,
      }} />

      {/* Avatar image (or fallback orb) */}
      <div style={{
        width: avatarSize, height: avatarSize, borderRadius: '50%',
        overflow: 'hidden', position: 'relative',
        background: imageUrl
          ? 'transparent'
          : `radial-gradient(circle at 35% 30%,
               hsl(${hue} 70% 55%) 0%,
               hsl(${(hue + 40) % 360} 50% 28%) 65%,
               hsl(${(hue + 80) % 360} 40% 12%) 100%)`,
        filter: state === 'ended' ? 'grayscale(0.6) brightness(0.7)' : 'none',
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.06), 0 0 0 1px rgba(255,255,255,0.04)`,
      }}>
        {imageUrl ? (
          <img src={imageUrl} alt="" style={{
            width: '100%', height: '100%', objectFit: 'cover', display: 'block',
          }} />
        ) : (
          // Soft top highlight so the fallback orb has depth
          <div style={{
            position: 'absolute', inset: 0,
            background: 'radial-gradient(circle at 40% 25%, rgba(255,255,255,0.35) 0%, transparent 45%)',
          }} />
        )}
      </div>

      {/* Keyframes defined once globally — safe to duplicate across components. */}
      <style>{`
        @keyframes hp-halo-breathe {
          0%, 100% { opacity: 0.30; transform: scale(1); }
          50%      { opacity: 0.85; transform: scale(1.06); }
        }
      `}</style>
    </div>
  );
}

Object.assign(window, { HPCallAvatar });
