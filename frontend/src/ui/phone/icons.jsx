// icons.jsx — minimal icon set for the HomePilot call surface.
//
// All 1.75 px stroke weight, 24-grid, rounded joins. Same visual
// weight as the lucide-react set HomePilot already uses elsewhere,
// so the call UI doesn't look like a foreign module.

const HPIcon = {
  phone: (size = 20, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>
    </svg>
  ),
  phoneEnd: (size = 20, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      {/* Handset pointing down + up-slope arrows on each side = universal "hang up" glyph. */}
      <path d="M4 14c5-5 11-5 16 0l-2 2-3-1v-2a9 9 0 0 0-6 0v2l-3 1-2-2z"
            transform="rotate(135 12 12)"/>
    </svg>
  ),
  mic: (size = 20, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="12" rx="3"/>
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
    </svg>
  ),
  micOff: (size = 20, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 9V6a3 3 0 0 1 6 0v5m0 4a3 3 0 0 1-6 0"/>
      <path d="M5 11a7 7 0 0 0 11.5 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3"/>
      <path d="M3 3l18 18"/>
    </svg>
  ),
  chat: (size = 20, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5h16v11H9l-5 4z"/>
    </svg>
  ),
  back: (size = 18, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 5l-7 7 7 7"/>
    </svg>
  ),
  minimize: (size = 16, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round">
      <path d="M5 12h14"/>
    </svg>
  ),
  speaker: (size = 20, color = 'currentColor') => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 9v6h4l5 4V5L8 9H4z"/>
      <path d="M17 8a5 5 0 0 1 0 8M19.5 5.5a8.5 8.5 0 0 1 0 13"/>
    </svg>
  ),
};

Object.assign(window, { HPIcon });
