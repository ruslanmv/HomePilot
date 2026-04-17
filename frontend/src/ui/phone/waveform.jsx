// waveform.jsx — audio-amplitude bars in the current state color.
//
// In production this will be driven by the TTS or mic analyser node
// (requestAnimationFrame → AnalyserNode.getByteFrequencyData). For
// the design mockups we deterministically seed the heights so the
// screenshot stays stable across re-renders — designer + dev get an
// identical frame to compare against.

function HPCallWaveform({
  bars = 28,
  height = 28,
  state = 'listening',     // drives color
  active = true,           // false → thin flat line (muted / ended)
  seed = 'homepilot',
}) {
  const color = hpCallStateColor(state);
  const opacity = active ? 1 : 0.3;

  // Stable pseudo-random heights in [0.15, 1.0] for a natural look.
  const heights = Array.from({ length: bars }, (_, i) => {
    const n = Math.sin(i * 0.8 + seed.length) * 0.4
            + Math.sin(i * 1.3 + seed.charCodeAt(0)) * 0.3
            + 0.55;
    return active ? Math.max(0.15, Math.min(1, Math.abs(n))) : 0.08;
  });

  return (
    <div style={{
      display: 'flex', gap: 3, alignItems: 'center', justifyContent: 'center',
      height, opacity,
    }}>
      {heights.map((h, i) => (
        <div key={i} style={{
          width: 3,
          height: `${h * 100}%`,
          background: color,
          borderRadius: 2,
          opacity: active ? 0.5 + h * 0.45 : 0.4,
          transition: 'height 80ms linear, opacity 80ms linear',
        }} />
      ))}
    </div>
  );
}

Object.assign(window, { HPCallWaveform });
