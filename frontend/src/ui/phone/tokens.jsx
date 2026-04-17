// tokens.jsx — HomePilot Call design tokens
//
// Apply these across every file in /phone. They pull directly from the
// existing HomePilot dark theme so the call surface feels native.
// Brand accent stays cyan (matches the rest of the app); telephony
// actions use emerald ("start, alive") and red-500 ("end, now") —
// the two universal call-button colors from FaceTime, WhatsApp, Meet.

const HP_CALL = {
  // Fonts — system stack same as the rest of HomePilot.
  font: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif',
  fontTabular: 'ui-monospace, SFMono-Regular, "Roboto Mono", Menlo, monospace',

  // Page / modal surfaces.
  backdrop: 'rgba(5, 5, 6, 0.72)',    // full-screen overlay behind the modal
  surface:  '#0b0b0c',                // card background (same as chat modal)
  surface2: '#121214',                // secondary buttons (mic/text toggles)
  surface3: 'rgba(255, 255, 255, 0.06)', // hover background on neutral buttons
  border:       'rgba(255, 255, 255, 0.08)',
  borderHover:  'rgba(255, 255, 255, 0.18)',

  // Text hierarchy.
  text:   'rgba(255, 255, 255, 0.92)',
  text2:  'rgba(255, 255, 255, 0.55)',
  text3:  'rgba(255, 255, 255, 0.35)',

  // Brand accent — reused everywhere in HomePilot.
  accent:      '#22d3ee',   // cyan-400 (buttons, focus rings)
  accentSoft:  'rgba(34, 211, 238, 0.22)',

  // Voice state colors. These drive the halo around the avatar AND the
  // label underneath. One color per state so the user can read the call
  // state from across the room without parsing words.
  stateListening: '#22d3ee',   // cyan-400   — mic open, AI waiting for you
  stateThinking:  '#a78bfa',   // violet-400 — backend processing
  stateSpeaking:  '#10b981',   // emerald-500 — AI's TTS playing
  stateError:     '#f87171',   // red-400    — reconnecting / error

  // Telephony actions.
  start:      '#10b981',   // emerald-500 — header Call button at rest
  startHover: '#059669',   // emerald-600
  startGlyph: '#052e23',   // dark emerald glyph on the start button
  end:        '#ef4444',   // red-500 — hang-up + header button mid-call
  endHover:   '#dc2626',   // red-600
};

// State → halo color helper.
function hpCallStateColor(state) {
  switch (state) {
    case 'listening': return HP_CALL.stateListening;
    case 'thinking':  return HP_CALL.stateThinking;
    case 'speaking':  return HP_CALL.stateSpeaking;
    case 'error':     return HP_CALL.stateError;
    case 'connecting':return HP_CALL.accent;
    case 'muted':     return HP_CALL.text3;    // neutral — muted is neither listening nor speaking
    case 'ended':     return HP_CALL.text3;
    default:          return HP_CALL.text2;
  }
}

// State → user-facing label (lowercase on purpose — matches HomePilot
// settings microcopy style: "test voice", "piper voice", etc.).
function hpCallStateLabel(state) {
  switch (state) {
    case 'connecting': return 'connecting';
    case 'listening':  return 'listening';
    case 'thinking':   return 'thinking';
    case 'speaking':   return 'speaking';
    case 'muted':      return 'microphone off';
    case 'error':      return 'reconnecting';
    case 'ended':      return 'call ended';
    default:           return '';
  }
}

Object.assign(window, { HP_CALL, hpCallStateColor, hpCallStateLabel });
